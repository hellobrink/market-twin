"""The Scenario tab of the coaching app: set a plan, pick a world, and watch one storyline play out."""

import altair as alt
import pandas as pd
import streamlit as st

from twin.assumptions import SHOCKS
from twin.scenario import FireRates, Plan, Season, SeasonPlan, World, play, play_range, random_world, replay_world

SHOCK_SHORT = {"subsidy": "Subsidy", "restriction": "Sales suspended", "competitor": "Rival arrives",
               "drought": "Drought", "tax_relief": "Tax relief"}
MARK_COLOURS = {"Severe fire": "#c0392b", "Bad fire": "#e67e22", "Subsidy": "#2a7a3b", "Tax relief": "#2a7a3b",
                "Sales suspended": "#6c3483", "Rival arrives": "#6c3483", "Drought": "#b7950b", "Plan change": "#7f8c8d"}
RECENT = {"3 seasons before (2024)": 3, "Last season": 1, "2 seasons before": 2, "Long ago": None}
RANGE_RUNS = 60


@st.cache_data(show_spinner=False)
def _story(_market, _fire_rates, _assumptions, model_key, plan: Plan, world: World, uncertain: str):
    return play(_market, _fire_rates, _assumptions, plan, world, farm_seed=0, uncertain=uncertain)


@st.cache_data(show_spinner=False)
def _range(_market, _fire_rates, _assumptions, model_key, plan: Plan, world: World, preset: str | None):
    if preset:
        def world_for(i):
            return random_world(_assumptions, preset, len(world.seasons), 10_000 + i, world.start_year, world.seasons_since_severe)
    else:
        def world_for(i):
            return world
    return play_range(_market, _fire_rates, _assumptions, plan, world_for, RANGE_RUNS)


def _plan_table(years: list[int], price: float, strategy: str) -> pd.DataFrame:
    return pd.DataFrame({"Season": years, "Price (R$/ha)": float(price), "Strategy": strategy,
                         "Sales effort (x)": 1.0, "Cooperative partnership": False})


def _plan_editor(label: str, key: str, years: list[int], price: float, strategies: list[str], segments: list[str]) -> Plan:
    st.markdown(f"**{label}**")
    chosen = st.multiselect("Sell to", segments, default=segments, key=f"{key}-segments",
                            format_func=lambda s: SEGMENT_NAMES.get(s, s))
    table = st.data_editor(
        _plan_table(years, price, "alert"),
        key=f"{key}-{years[0]}-{len(years)}",
        hide_index=True,
        width="stretch",
        disabled=["Season"],
        column_config={
            "Season": st.column_config.NumberColumn(format="%d"),
            "Price (R$/ha)": st.column_config.NumberColumn(min_value=50, max_value=3000, step=50, format="R$%d",
                                                           help="Price per hectare per treatment"),
            "Strategy": st.column_config.SelectboxColumn(options=strategies, help="When farms treat"),
            "Sales effort (x)": st.column_config.NumberColumn(min_value=0.0, max_value=3.0, step=0.5,
                                                              help="Multiplies the outside push from sales, demos and field days"),
            "Cooperative partnership": st.column_config.CheckboxColumn(help="Boosts word of mouth among cooperative members"),
        },
    )
    seasons = tuple(
        SeasonPlan(float(r["Price (R$/ha)"]), str(r["Strategy"]), float(r["Sales effort (x)"]), bool(r["Cooperative partnership"]))
        for _, r in table.iterrows()
    )
    return Plan(seasons, frozenset(chosen))


def _custom_world(n: int, start_year: int, recent: int | None) -> World:
    table = pd.DataFrame({"Season": [start_year + i for i in range(n)], "Fire": "normal",
                          **{SHOCK_SHORT[s]: False for s in SHOCKS}})
    edited = st.data_editor(
        table, key=f"custom-world-{start_year}-{n}", hide_index=True, width="stretch", disabled=["Season"],
        column_config={"Season": st.column_config.NumberColumn(format="%d"),
                       "Fire": st.column_config.SelectboxColumn(options=["normal", "severe"])},
    )
    seasons = tuple(
        Season(str(r["Fire"]), frozenset(s for s in SHOCKS if r[SHOCK_SHORT[s]])) for _, r in edited.iterrows()
    )
    return World(start_year, seasons, recent, "custom world")


def _markers(story, plan: Plan) -> pd.DataFrame:
    rows = []
    for i, r in story.seasons.iterrows():
        if r["fire_label"].startswith("Severe"):
            rows.append((r["year"], "Severe fire"))
        elif r["fire_label"].startswith("Bad"):
            rows.append((r["year"], "Bad fire"))
        for s in filter(None, r["shocks"].split(", ")):
            rows.append((r["year"], SHOCK_SHORT[s]))
        if i > 0 and plan.seasons[i] != plan.seasons[i - 1]:
            rows.append((r["year"], "Plan change"))
    df = pd.DataFrame(rows, columns=["year", "event"])
    df["year"] = df["year"].astype(str)
    df["row"] = df.groupby("year").cumcount()
    return df


def _timeline(story_a, story_b, band: pd.DataFrame, markers: pd.DataFrame, column: str, title: str, scale: float = 1.0):
    lines = [story_a.seasons.assign(plan="Your plan")]
    if story_b is not None:
        lines.append(story_b.seasons.assign(plan="Alternative plan"))
    lines = pd.concat(lines)[["year", "plan", column]]
    lines["year"] = lines["year"].astype(str)
    lines["value"] = lines[column] / scale
    rng = pd.DataFrame({"year": band.index.astype(str), "low": band[f"{column}_p10"] / scale, "high": band[f"{column}_p90"] / scale})
    x = alt.X("year:O", title=None)
    area = alt.Chart(rng).mark_area(opacity=0.18, color="#7a8aa0").encode(x=x, y=alt.Y("low:Q", title=title), y2="high:Q")
    plan_line = alt.Chart(lines).mark_line(point=True, strokeWidth=2.5).encode(
        x=x, y="value:Q",
        color=alt.Color("plan:N", title=None, scale=alt.Scale(domain=["Your plan", "Alternative plan"], range=["#1f5fa8", "#d35400"]),
                        legend=alt.Legend(orient="top")),
        strokeDash=alt.StrokeDash("plan:N", scale=alt.Scale(domain=["Your plan", "Alternative plan"], range=[[1, 0], [6, 3]]), legend=None),
        tooltip=["year", "plan", alt.Tooltip("value:Q", format=",.1f")],
    )
    chart = alt.layer(area, plan_line)
    if not markers.empty:
        colours = alt.Scale(domain=list(MARK_COLOURS), range=list(MARK_COLOURS.values()))
        rules = alt.Chart(markers).mark_rule(strokeDash=[3, 3], opacity=0.6).encode(
            x=x, color=alt.Color("event:N", scale=colours, legend=None), tooltip=["year", "event"])
        labels = alt.Chart(markers.assign(px=6 + 13 * markers["row"])).mark_text(  # stacked in pixels when a season has several events
            align="left", dx=3, fontSize=10, baseline="top").encode(
            x=x, y=alt.Y("px:Q", scale=None, axis=None), text="event:N", color=alt.Color("event:N", scale=colours, legend=None))
        # The range and plan lines share one y scale; only the pixel-placed labels and event colours stand apart.
        chart = alt.layer(alt.layer(rules, area, plan_line).resolve_scale(color="independent"), labels).resolve_scale(
            y="independent", color="independent")
    st.altair_chart(chart.properties(height=300), width="stretch")


SEGMENT_NAMES: dict[str, str] = {}


def render(market, data, assumptions, model_key, names: pd.Series, points: pd.DataFrame, bubble_map, money_m, segment_names):
    SEGMENT_NAMES.update(segment_names)
    fire_rates = _fire_rates(market, data)
    st.markdown(
        "Play one storyline season by season. **Your plan** sets the levers you control. **The world** sets events "
        "you don't. The sidebar's model settings (containment, hurdle, adoption rates) apply here too; price and "
        "strategy come from your plan."
    )
    world_col, plan_col = st.columns([1, 1.3], gap="large")
    with world_col:
        st.subheader("The world")
        mode = st.radio("Events", ["Easy", "Normal", "Hard", "Replay 2015-2024", "Custom"], index=1, horizontal=True,
                        help="Easy, normal and hard draw events at different rates. Replay plays the real fire seasons of 2015-2024.")
        preset = mode.lower() if mode in ("Easy", "Normal", "Hard") else None
        if mode.startswith("Replay"):
            n, start = 10, 2015
            recent = RECENT[st.selectbox("Last severe season before the start", list(RECENT), index=3)]
            world = replay_world(2015, 2024, recent)
            st.caption("Real MapBiomas burn rates for each year. No shocks: the replay shows fire alone.")
        else:
            n = st.slider("Seasons", 3, 15, 10)
            start = assumptions.adoption.start_year
            recent = RECENT[st.selectbox("Last severe season before the start", list(RECENT), index=0)]
            if preset:
                st.session_state.setdefault("world_seed", 1)
                c1, c2 = st.columns([1, 1])
                if c2.button("New random world", width="stretch"):
                    st.session_state["world_seed"] += 1
                seed = c1.number_input("World number", min_value=1, step=1, key="world_seed")
                world = random_world(assumptions, preset, n, int(seed), start, recent)
                chances = assumptions.scenario.presets[preset]
                st.caption("Chance each season: " + ", ".join(
                    [f"severe fire {chances['severe']:.0%}"] + [f"{SHOCK_SHORT[s].lower()} {chances[s]:.0%}" for s in SHOCKS if chances[s]]))
            else:
                world = _custom_world(n, start, recent)
        uncertain = st.radio("Uncertain inputs in the story", ["Base values", "Drawn for this world"], horizontal=True,
                             help="Base values keep the story about events and decisions. Drawn values add the model's own uncertainty.")
        uncertain = "base" if uncertain == "Base values" else "drawn"

    years = [start + i for i in range(n)]
    with plan_col:
        st.subheader("Your plan")
        st.caption("Edit any season to change the plan from that year, for example a lower launch price or a partnership from year 3.")
        strategies = list(assumptions.strategies)
        plan_a = _plan_editor("Plan", "plan-a", years, assumptions.product["product_cost_per_ha"].base, strategies, list(assumptions.segments))
        compare = st.checkbox("Compare with an alternative plan: same events, same luck")
        plan_b = _plan_editor("Alternative plan", "plan-b", years, 400, strategies, list(assumptions.segments)) if compare else None

    with st.spinner("Playing the seasons"):
        story_a = _story(market, fire_rates, assumptions, model_key, plan_a, world, uncertain)
        story_b = _story(market, fire_rates, assumptions, model_key, plan_b, world, uncertain) if plan_b else None
        band = _range(market, fire_rates, assumptions, model_key, plan_a, world, preset)

    st.divider()
    s = story_a.seasons
    farmer_return = (s["avoided_loss"].sum() + s["water_value"].sum() - s["farmer_spend"].sum()) / max(s["farmer_spend"].sum(), 1)
    c1, c2, c3, c4 = st.columns(4)

    def delta(column, agg, fmt):
        if story_b is None:
            return None
        diff = agg(s[column]) - agg(story_b.seasons[column])
        return f"{fmt(diff)} vs alternative"

    c1.metric(f"Users in {years[-1]}", f"{s['adopters'].iloc[-1]:,}", delta("adopters", lambda c: c.iloc[-1], lambda d: f"{d:+,.0f}"))
    c2.metric("Revenue over the run", money_m(s["revenue"].sum()), delta("revenue", lambda c: c.sum(), lambda d: ("+" if d >= 0 else "-") + money_m(abs(d))))
    c3.metric("Fires held by treated farms", f"{s['fires_held'].sum():,}", delta("fires_held", lambda c: c.sum(), lambda d: f"{d:+,.0f}"))
    c4.metric("Users' return on what they spent", f"{farmer_return:.0%}", "avoided losses and water, over the run", delta_color="off")

    markers = _markers(story_a, plan_a)
    left, right = st.columns(2)
    with left:
        st.markdown(f"**Farms using NoFire.** Shaded: P10 to P90 of {RANGE_RUNS} runs " +
                    ("of other worlds at the same difficulty" if preset else "of this world with uncertain inputs drawn"))
        _timeline(story_a, story_b, band, markers, "adopters", "Farms")
    with right:
        st.markdown("**Revenue per season**, R$ millions")
        _timeline(story_a, story_b, band, markers, "revenue", "R$ millions", scale=1e6)

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("**What happened**")
        b_seasons = story_b.seasons.set_index("year") if story_b is not None else None
        for entry in story_a.log:
            lines = [f"**{entry['year']}** · {entry['fire']}"]
            lines += [f"- {note}" for note in entry["notes"]]
            if entry["fires_held"]:
                where = ", ".join(f"{names.get(code, code)} {count}" for code, count in entry["saves"])
                lines.append(f"- {entry['fires_held']} treated farm{'s' if entry['fires_held'] > 1 else ''} held a fire line" + (f": {where}" if where else ""))
            change = f"{entry['new']:+d} new, {-entry['stopped'] if entry['stopped'] else 0} stopped" + (f", {entry['lost_to_rival']} lost to the rival" if entry["lost_to_rival"] else "")
            lines.append(f"- Users: {entry['adopters']:,} ({change})")
            if b_seasons is not None:
                lines.append(f"- Alternative plan: {b_seasons.loc[entry['year'], 'adopters']:,} users")
            st.markdown("  \n".join(lines[:1]) + "\n" + "\n".join(lines[1:]))
    with right:
        st.markdown("**Where treated farms held fires**, over the run")
        bubble_map(pd.Series(story_a.saves_by_municipality, index=market.municipalities), points, names, (192, 57, 43))
        st.markdown("**Season by season**")
        table = s[["year", "fire_label", "farmer_price", "adopters", "new", "stopped", "fires_held", "revenue"]].rename(columns={
            "year": "Season", "fire_label": "Fire", "farmer_price": "Farmer pays", "adopters": "Users", "new": "New",
            "stopped": "Stopped", "fires_held": "Fires held", "revenue": "Revenue"})
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "Season": st.column_config.NumberColumn(format="%d"),
            "Farmer pays": st.column_config.NumberColumn(format="R$%d"),
            "Revenue": st.column_config.NumberColumn(format="localized")})

    st.caption("Fire seasons rest on MapBiomas data. Subsidy, sales suspension, rival, drought and tax relief have illustrative "
               "sizes set in the assumptions file, and most behavioural inputs are still placeholders.")


@st.cache_resource
def _fire_rates(_market, _data):
    return FireRates(_market, _data)
