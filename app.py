"""Coaching app for the market twin: NoFire preventive fire treatment in São Paulo.

Run from the repo root:

    .venv/bin/streamlit run app.py
"""

import altair as alt
import numpy as np
import pydeck as pdk
import pandas as pd
import streamlit as st

from twin.adoption import build_market, drivers, simulate_adoption, yearly_summary
from twin.assumptions import load
from twin.overrides import override
from twin.population import PROCESSED, StateData, add_risk, build_population, evaluate
from twin.report import DEFAULT_ASSUMPTIONS
from twin.roi import INPUTS, base_case, tornado
from twin import scenario_view

STATE = "SP"

LABELS = {
    "product_cost_per_ha": "Product price",
    "containment_rate": "Containment rate",
    "water_saving_share": "Water saving",
    "application_cost_per_ha": "Application cost",
    "water_cost_per_m3": "Water cost",
    "farm_area_ha": "Farm area",
    "treated_share": "Share of farm treated",
    "annual_fire_probability": "Chance of fire",
    "burned_area_if_fire_share": "Share burned if fire",
    "value_at_risk_per_ha": "Value at risk per ha",
    "baseline_water_m3_per_ha": "Water used today",
    "applications_per_season": "Treatments per season",
    "timing_coverage": "Fires met by a treatment",
    "severe_seasons": "Severe seasons in the decade",
    "severe_year_probability": "Chance of a severe season",
    "risk_memory_half_life": "Memory of a bad year",
    "innovation_rate": "Outside push (Bass p)",
    "imitation_rate": "Peer imitation (Bass q)",
    "non_member_peer_weight": "Non-member peer weight",
    "churn_when_unprofitable": "Churn when unprofitable",
    "sugarcane_fire_loss_share": "Cane loss share",
    "sugarcane_coop_share": "Cane cooperative share",
}
SEGMENT_LABELS = {
    "sugarcane_ground": "Sugarcane, ground",
    "smallholder_ground": "Smallholder, own truck",
    "smallholder_drone": "Smallholder, drone",
    "remote_ranch_drone": "Large ranch, drone",
}

st.set_page_config(page_title="Market twin: NoFire in São Paulo", layout="wide")


@st.cache_resource
def base_assumptions():
    return load(DEFAULT_ASSUMPTIONS)


@st.cache_resource
def state_data():
    data = StateData.load(STATE)
    farms = build_population(data)
    points = pd.read_csv(PROCESSED / STATE.lower() / "municipality_points.csv").set_index("municipality")
    names = data.municipalities.set_index("municipality")["name"]
    return data, farms, points, names


@st.cache_resource
def market():
    data, farms, _, _ = state_data()
    return build_market(farms, data, base_assumptions())


@st.cache_resource
def farms_at_risk(scenario: str):
    data, farms, _, _ = state_data()
    return add_risk(farms, data, base_assumptions(), scenario)


def what_if(changes: dict) -> object:
    return override(base_assumptions(), **{k: v for k, v in changes.items() if v})


@st.cache_data(show_spinner=False)
def run_adoption(strategy: str, changes_key: tuple, runs: int, peers: bool):
    changes = {section: dict(items) for section, items in changes_key}
    seasons, draws, by_muni = simulate_adoption(market(), what_if(changes), strategy, runs=runs, peers=peers)
    return seasons, draws, by_muni


def money_m(x: float) -> str:
    return f"R${x / 1e6:,.1f}m" if abs(x) >= 1e6 else f"R${x / 1e3:,.0f}k"


def bubble_map(counts: pd.Series, points: pd.DataFrame, names: pd.Series, color: tuple[int, int, int]):
    """Bubbles sized by count on a fixed view of the whole state, so a single point doesn't fill the map."""
    df = points.join(counts.rename("count"), how="inner")
    df = df[df["count"] > 0].copy()
    if df.empty:
        st.info("No buyers to map under these settings.")
        return
    df["radius"] = np.sqrt(df["count"] / df["count"].max()) * 30_000  # busiest municipality gets a 30 km bubble
    df["name"] = df.index.map(names)
    df["label"] = df["count"].map(lambda c: f"{c:,.1f}" if c % 1 else f"{c:,.0f}")
    layer = pdk.Layer("ScatterplotLayer", data=df.reset_index(), get_position="[lon, lat]", get_radius="radius",
                      get_fill_color=[*color, 150], pickable=True)  # radius is in metres by default
    view = pdk.ViewState(latitude=-22.3, longitude=-48.7, zoom=5.4)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, map_style=None, tooltip={"text": "{name}: {label}"}), height=380)
    top = df.sort_values("count", ascending=False).head(8)
    st.caption("Most buyers: " + ", ".join(f"{names.get(code, code)} ({count:,.0f})" for code, count in top["count"].items()))


def fan_chart(summary: pd.DataFrame, prefix: str, title: str, scale: float = 1.0):
    df = pd.DataFrame({
        "year": summary.index.astype(str),
        "low": summary[f"{prefix}_p10"] / scale,
        "median": summary[f"{prefix}_median"] / scale,
        "high": summary[f"{prefix}_p90"] / scale,
    })
    base = alt.Chart(df).encode(x=alt.X("year:O", title=None))
    band = base.mark_area(opacity=0.25).encode(y=alt.Y("low:Q", title=title), y2="high:Q", tooltip=["year", "low", "median", "high"])
    line = base.mark_line(point=True).encode(y="median:Q")
    st.altair_chart((band + line).properties(height=280), width="stretch")


# ---------------------------------------------------------------- controls
a0 = base_assumptions()
data, farms, points, names = state_data()

st.sidebar.title("Model settings")
strategy = st.sidebar.radio(
    "Treatment strategy", list(a0.strategies), index=list(a0.strategies).index("alert"),
    format_func=lambda s: {"scheduled": "Scheduled", "alert": "On fire alerts"}.get(s, s),
    help="\n\n".join(f"{k}: {v}" for k, v in a0.strategies.items()),
)
price = st.sidebar.slider("Product price, R$ per ha per application", 100, 1500, int(a0.product["product_cost_per_ha"].base), 50)
containment = st.sidebar.slider("Containment rate", 0.40, 0.85, float(a0.product["containment_rate"].base), 0.05,
                                help="Share of fire spread a treated strip stops. The pilot reported up to 85%.")
hurdle = st.sidebar.slider("Farmer's ROI hurdle", 0.0, 1.5, float(a0.buyer["roi_hurdle"].base), 0.1,
                           help="Return a farmer needs before buying. 0.5 means R$1.50 back for every R$1.")
with st.sidebar.expander("Adoption over time"):
    rates = a0.adoption.rates
    severe_p = st.slider("Chance a season is severe", 0.0, 0.3, float(rates["severe_year_probability"].base), 0.05)
    memory = st.slider("Memory of a bad year (seasons to halve)", 0.5, 6.0, float(rates["risk_memory_half_life"].base), 0.5)
    push = st.slider("Outside push, Bass p", 0.0, 0.05, float(rates["innovation_rate"].base), 0.005, format="%.3f")
    imitation = st.slider("Peer imitation, Bass q", 0.0, 0.8, float(rates["imitation_rate"].base), 0.05)
    coop = st.slider("Cane farms in a cooperative", 0.0, 1.0, float(a0.adoption.coop_member_share["sugarcane_ground"].base), 0.05)
    runs = st.select_slider("Monte Carlo runs", [50, 100, 200, 500], value=100)
    compare_peers = st.checkbox("Compare with no peer effects", value=True)

# Only inputs moved away from their base value are fixed; the rest keep their ranges.
chosen = {
    "product": {"product_cost_per_ha": price, "containment_rate": containment},
    "buyer": {"roi_hurdle": hurdle},
    "adoption_rates": {"severe_year_probability": severe_p, "risk_memory_half_life": memory,
                       "innovation_rate": push, "imitation_rate": imitation},
    "coop_member_share": {"sugarcane_ground": coop},
}
base_values = {
    "product": {k: a0.product[k].base for k in chosen["product"]},
    "buyer": {"roi_hurdle": a0.buyer["roi_hurdle"].base},
    "adoption_rates": {k: rates[k].base for k in chosen["adoption_rates"]},
    "coop_member_share": {"sugarcane_ground": a0.adoption.coop_member_share["sugarcane_ground"].base},
}
changes = {
    section: {k: float(v) for k, v in values.items() if not np.isclose(v, base_values[section][k])}
    for section, values in chosen.items()
}
changes_key = tuple((section, tuple(sorted(items.items()))) for section, items in changes.items())
assumptions = what_if(changes)
moved = [LABELS.get(k, k) if k != "sugarcane_ground" else "Cane cooperative share" for items in changes.values() for k in items]
st.sidebar.caption(
    ("Fixed for this what-if: " + ", ".join(moved) + ". " if moved else "")
    + "Everything else keeps its range in the adoption runs."
)

# ---------------------------------------------------------------- page
st.title("NoFire in São Paulo: market twin")
st.caption(
    f"{len(farms):,} synthetic farms from the 2017 census, fire risk from MapBiomas burned area 2015-2024. "
    "Most behavioural inputs are still placeholders; see the Assumptions tab."
)
scenario_tab, market_tab, adoption_tab, roi_tab, assumptions_tab = st.tabs(
    ["Scenario", "Market today", "Adoption over time", "Farm ROI", "Assumptions"])

with scenario_tab:
    scenario_view.render(market(), data, assumptions, changes_key, names, points, bubble_map, money_m, SEGMENT_LABELS)

with market_tab:
    scenarios = list(a0.fire_scenarios)
    scenario = st.radio("Fire scenario", scenarios, horizontal=True,
                        format_func=lambda s: f"{s} ({a0.fire_scenarios[s].label()})")
    st.caption(a0.fire_scenarios[scenario].description)
    evaluated = evaluate(farms_at_risk(scenario), assumptions, strategy)
    buyers = evaluated[evaluated["clears_hurdle"]]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Farms in the market", f"{len(evaluated):,}")
    c2.metric("Would buy", f"{len(buyers):,}", f"{len(buyers) / len(evaluated):.1%} of farms", delta_color="off")
    c3.metric("Buyers' spend", money_m(buyers["product_spend"].sum()), "per season", delta_color="off")
    c4.metric("Cane median ROI", f"{evaluated.loc[evaluated['segment'] == 'sugarcane_ground', 'roi'].median():.0%}")

    table = evaluated.groupby("segment").agg(
        farms=("roi", "size"), median_roi=("roi", "median"), buyers=("clears_hurdle", "sum"),
        burned_a_year=("burn_rate", "median"),
    )
    table["spend"] = buyers.groupby("segment")["product_spend"].sum().reindex(table.index).fillna(0)
    table.index = table.index.map(SEGMENT_LABELS)
    st.dataframe(
        table.rename(columns={"farms": "Farms", "median_roi": "Median ROI", "buyers": "Would buy",
                              "burned_a_year": "Burned a year (median)", "spend": "Product spend, R$"}),
        width="stretch",
        column_config={
            "Median ROI": st.column_config.NumberColumn(format="percent"),
            "Burned a year (median)": st.column_config.NumberColumn(format="percent"),
            "Product spend, R$": st.column_config.NumberColumn(format="localized"),
        },
    )
    st.subheader("Where the buyers are")
    bubble_map(buyers.groupby("municipality").size(), points, names, (212, 39, 30))

with adoption_tab:
    years = f"{a0.adoption.start_year}-{a0.adoption.start_year + a0.adoption.seasons - 1}"
    st.caption(f"{runs} runs, {years}. Each run draws the uncertain inputs and a sequence of normal and severe fire seasons.")
    with st.spinner("Running the simulation"):
        seasons, draws, by_muni = run_adoption(strategy, changes_key, runs, True)
        summary = yearly_summary(seasons)
        final = seasons[seasons["season"] == seasons["season"].max()]
        final_total = final.groupby("run")["adopters"].sum()
        if compare_peers:
            alone, _, _ = run_adoption(strategy, changes_key, runs, False)
            alone_total = alone[alone["season"] == alone["season"].max()].groupby("run")["adopters"].sum()

    last = summary.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Users in {summary.index[-1]}", f"{last['adopters_median']:,.0f}", "median", delta_color="off")
    c2.metric("Optimistic case", f"{last['adopters_p90']:,.0f}", "P90", delta_color="off")
    c3.metric(f"Revenue in {summary.index[-1]}", money_m(last["revenue_median"]), "median", delta_color="off")
    if compare_peers:
        c4.metric("Added by peers", f"{final_total.median() - alone_total.median():+,.0f}",
                  f"{alone_total.median():,.0f} without them", delta_color="off")

    left, right = st.columns(2)
    with left:
        st.markdown("**Farms using NoFire**, median with P10 to P90 band")
        fan_chart(summary, "adopters", "Farms")
    with right:
        st.markdown("**Revenue per season**, R$ millions")
        fan_chart(summary, "revenue", "R$ millions", scale=1e6)

    left, right = st.columns(2)
    with left:
        st.markdown("**What moves the outcome most**")
        drv = drivers(seasons, draws).head(8).rename(index=LABELS).rename("correlation").reset_index()
        drv.columns = ["input", "correlation"]
        st.altair_chart(
            alt.Chart(drv).mark_bar().encode(
                x=alt.X("correlation:Q", title="Rank correlation with final adopters", scale=alt.Scale(domain=[-1, 1])),
                y=alt.Y("input:N", sort=None, title=None, axis=alt.Axis(labelLimit=240)),
                color=alt.condition("datum.correlation > 0", alt.value("#2a7a3b"), alt.value("#b5402a")),
                tooltip=["input", alt.Tooltip("correlation:Q", format=".2f")],
            ).properties(height=260),
            width="stretch",
        )
        st.caption("Inputs fixed for this what-if don't vary, so they drop out of this chart.")
    with right:
        st.markdown(f"**Where adopters are in {summary.index[-1]}**, mean across runs")
        bubble_map(pd.Series(by_muni, index=market().municipalities), points, names, (31, 95, 168))

    by_segment = final.groupby("segment")[["adopters", "willing"]].median()
    by_segment.index = by_segment.index.map(SEGMENT_LABELS)
    st.dataframe(by_segment.rename(columns={"adopters": "Using it (median)", "willing": "Would profit (median)"}), width="stretch")

with roi_tab:
    st.caption("A single typical farm from each segment, using the segment ranges in the assumptions file rather than census data.")
    segment = st.selectbox("Segment", list(a0.segments), format_func=lambda s: SEGMENT_LABELS.get(s, s))
    ranges = assumptions.inputs_for(segment, strategy)
    case = base_case(ranges)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cost per season", money_m(case["cost"]))
    c2.metric("Avoided fire loss", money_m(case["avoided_loss"]))
    c3.metric("ROI", f"{case['roi']:.0%}")
    c4.metric("Break-even price", f"R${case['breakeven_product_cost_per_ha']:,.0f}", "per ha, per treatment", delta_color="off")
    swings = tornado(ranges).head(8)
    swings["input"] = swings["input"].map(LABELS).fillna(swings["input"])
    swings["low"] = swings[["at_low", "at_high"]].min(axis=1)
    swings["high"] = swings[["at_low", "at_high"]].max(axis=1)
    st.markdown("**Which inputs swing this farm's ROI most** (each from its low to its high value, others at base)")
    bars = alt.Chart(swings).mark_bar(color="#7a8aa0").encode(
        x=alt.X("low:Q", title="ROI", axis=alt.Axis(format="%")), x2="high:Q",
        y=alt.Y("input:N", sort=None, title=None, axis=alt.Axis(labelLimit=240)),
        tooltip=["input", alt.Tooltip("at_low:Q", format=".0%"), alt.Tooltip("at_high:Q", format=".0%"), "status"],
    )
    base_rule = alt.Chart(pd.DataFrame({"roi": [case["roi"]]})).mark_rule(color="black").encode(x="roi:Q")
    st.altair_chart((bars + base_rule).properties(height=280), width="stretch")

with assumptions_tab:
    rows = []

    def add(section, name, r):
        rows.append({"section": section, "input": name, "low": r.low, "base": r.base, "high": r.high, "status": r.status, "note": r.note})

    for name, r in assumptions.product.items():
        add("product", name, r)
    for mode, items in assumptions.delivery.items():
        for name, r in items.items():
            add(f"delivery: {mode}", name, r)
    for name, r in {**assumptions.buyer, **assumptions.population}.items():
        add("buyer and population", name, r)
    for key, seg in assumptions.segments.items():
        for name, r in seg.params.items():
            add(SEGMENT_LABELS.get(key, key), name, r)
        for strat, items in seg.strategies.items():
            for name, r in items.items():
                add(f"{SEGMENT_LABELS.get(key, key)}: {strat}", name, r)
    for name, r in assumptions.adoption.rates.items():
        add("adoption", name, r)
    for key, r in assumptions.adoption.coop_member_share.items():
        add("adoption: cooperative share", key, r)
    for name, r in assumptions.scenario.rates.items():
        add("scenario mode", name, r)
    table = pd.DataFrame(rows)
    counts = table["status"].value_counts()
    st.write(" · ".join(f"**{counts.get(s, 0)}** {s}" for s in ["placeholder", "pilot", "public", "interview", "scenario"] if counts.get(s, 0)))
    status = st.multiselect("Show", sorted(table["status"].unique()), default=sorted(table["status"].unique()))
    st.dataframe(table[table["status"].isin(status)], width="stretch", hide_index=True)
    st.caption("Edit assumptions/nofire_brazil.yaml to change ranges permanently, and set status to interview or public when a number comes from real data.")
