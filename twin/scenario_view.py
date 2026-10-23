"""The Scenario tab of the coaching app: set a plan, pick a world, and watch one storyline play out."""

import time

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
AUTO_PACE = 1.5  # seconds between seasons in automatic play
FIRE_ICONS = {"Severe": "🔥", "Bad": "🟠", "Quiet": "🟢", "Normal": "⚪"}
SHOCK_ICONS = {"subsidy": "💰", "restriction": "⛔", "competitor": "⚔️", "drought": "💧", "tax_relief": "🧾"}


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


def _timeline(lines: pd.DataFrame, band: pd.DataFrame, markers: pd.DataFrame, column: str, title: str,
              x_domain: list[str], y_max: float, scale: float = 1.0) -> alt.Chart:
    """Plan lines over the shaded range, with event markers. Axes are fixed so the chart grows without rescaling."""
    lines = lines[["year", "plan", column]].assign(year=lambda d: d["year"].astype(str), value=lambda d: d[column] / scale)
    rng = pd.DataFrame({"year": band.index.astype(str), "low": band[f"{column}_p10"] / scale, "high": band[f"{column}_p90"] / scale})
    x = alt.X("year:O", title=None, scale=alt.Scale(domain=x_domain))
    y_scale = alt.Scale(domain=[0, y_max / scale])
    area = alt.Chart(rng).mark_area(opacity=0.18, color="#7a8aa0").encode(x=x, y=alt.Y("low:Q", title=title, scale=y_scale), y2="high:Q")
    plans = [p for p in ("Your plan", "Alternative plan") if p in set(lines["plan"])]
    plan_line = alt.Chart(lines).mark_line(point=True, strokeWidth=2.5).encode(
        x=x, y=alt.Y("value:Q", scale=y_scale),
        color=alt.Color("plan:N", title=None, scale=alt.Scale(domain=plans, range=["#1f5fa8", "#d35400"][: len(plans)]),
                        legend=alt.Legend(orient="top")),
        strokeDash=alt.StrokeDash("plan:N", scale=alt.Scale(domain=plans, range=[[1, 0], [6, 3]][: len(plans)]), legend=None),
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
    return chart.properties(height=300)


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

    key = (plan_a, plan_b, world, uncertain, model_key)
    if st.session_state.get("scenario_key") != key:  # any change to the setup starts the story again
        st.session_state.update(scenario_key=key, scenario_shown=0, scenario_autoplay=False, scenario_revealed=False)
    shown = st.session_state["scenario_shown"]

    st.divider()
    c1, c2, c3 = st.columns([1.4, 1, 1], vertical_alignment="center")
    mode = c1.radio("How to play", ["Step by step", "Automatic"], horizontal=True,
                    help="Step by step pauses after each season until you click Next. Automatic plays the seasons on its own.")
    if shown < n:
        if mode == "Step by step":
            c2.button("▶ Start" if shown == 0 else f"Next season ▶ ({years[shown]})", type="primary", width="stretch",
                      on_click=_advance, args=(n,), key="scenario-next-top")
        else:
            c2.button("▶ Play" if shown == 0 else "▶ Play the rest", type="primary", width="stretch", on_click=_autoplay)
    if shown:
        c3.button("↺ Restart", width="stretch", on_click=_restart)
    autoplay = st.session_state["scenario_autoplay"]
    if not (shown or autoplay):
        st.info(f"Set the world and your plan, then press **{'Start' if mode == 'Step by step' else 'Play'}** "
                f"to watch {years[0]}-{years[-1]} unfold season by season.")
        return

    with st.spinner("Setting up the seasons"):
        story_a = _story(market, fire_rates, assumptions, model_key, plan_a, world, uncertain)
        story_b = _story(market, fire_rates, assumptions, model_key, plan_b, world, uncertain) if plan_b else None
        band = _range(market, fire_rates, assumptions, model_key, plan_a, world, preset)

    strip = st.empty()
    timeline_col, panel_col = st.columns([1, 1.15], gap="large")
    with timeline_col:
        st.markdown("**Timeline**")
        cards = [st.empty() for _ in range(n)]
        bottom = st.empty()
    with panel_col:
        metrics = st.empty()
        st.markdown(f"**Farms using NoFire.** Shaded: P10 to P90 of {RANGE_RUNS} runs " +
                    ("of other worlds at the same difficulty" if preset else "of this world with uncertain inputs drawn"))
        users_chart = st.empty()
        st.markdown("**Revenue per season**, R$ millions")
        revenue_chart = st.empty()
        st.markdown("**Where treated farms held fires** so far")
        map_box = st.empty()
    st.markdown("**Season by season**")
    table_box = st.empty()
    st.caption("Fire seasons rest on MapBiomas data. Subsidy, sales suspension, rival, drought and tax relief have illustrative "
               "sizes set in the assumptions file, and most behavioural inputs are still placeholders.")

    stories = [story_a.seasons.assign(plan="Your plan")] + ([story_b.seasons.assign(plan="Alternative plan")] if story_b else [])
    all_lines = pd.concat(stories)
    x_domain = [str(y) for y in years]
    limits = {c: 1.05 * max(all_lines[c].max(), band[f"{c}_p90"].max(), 1) for c in ("adopters", "revenue")}
    markers = _markers(story_a, plan_a)
    seasons = story_a.seasons
    b_index = story_b.seasons.set_index("year") if story_b else None
    changed = [i > 0 and plan_a.seasons[i] != plan_a.seasons[i - 1] for i in range(n)]

    def draw_strip(t: int):
        with strip.container():
            cols = st.columns(n)
            for i, col in enumerate(cols):
                if i < t:
                    row = seasons.iloc[i]
                    icons = _fire_icon(row["fire_label"]) + "".join(SHOCK_ICONS[x] for x in filter(None, row["shocks"].split(", ")))
                    icons += "🔧" if changed[i] else ""
                    col.markdown(f"<div style='text-align:center'><b>{years[i]}</b><br>{icons}<br>"
                                 f"<span style='font-size:0.8em'>{row['adopters']:,} users</span></div>", unsafe_allow_html=True)
                else:
                    col.markdown(f"<div style='text-align:center;color:#aaa'>{years[i]}<br>·</div>", unsafe_allow_html=True)
            st.caption("🔥 severe fire · 🟠 bad fire · ⚪ normal · 🟢 quiet · 💰 subsidy · ⛔ sales suspended · ⚔️ rival · "
                       "💧 drought · 🧾 tax relief · 🔧 plan change")

    def draw_card(i: int):
        entry, row = story_a.log[i], seasons.iloc[i]
        label = row["fire_label"]
        box = (cards[i].error if label.startswith("Severe") else cards[i].warning if label.startswith("Bad")
               else cards[i].success if label.startswith("Quiet") else cards[i].info)
        box(_card_text(entry, row, names, b_index, money_m))

    def draw_panel(t: int):
        sa = seasons.iloc[:t]
        sb = story_b.seasons.iloc[:t] if story_b else None
        spend = sa["farmer_spend"].sum()
        farmer_return = (sa["avoided_loss"].sum() + sa["water_value"].sum() - spend) / spend if spend else None

        def delta(column, agg, fmt):
            if sb is None:
                return None
            return f"{fmt(agg(sa[column]) - agg(sb[column]))} vs alternative"

        with metrics.container():
            c1, c2 = st.columns(2)
            c3, c4 = st.columns(2)
            c1.metric(f"Users in {years[t - 1]}", f"{sa['adopters'].iloc[-1]:,}", delta("adopters", lambda c: c.iloc[-1], lambda d: f"{d:+,.0f}"))
            c2.metric("Revenue so far", money_m(sa["revenue"].sum()),
                      delta("revenue", lambda c: c.sum(), lambda d: ("+" if d >= 0 else "-") + money_m(abs(d))))
            c3.metric("Fires held", f"{sa['fires_held'].sum():,}", delta("fires_held", lambda c: c.sum(), lambda d: f"{d:+,.0f}"))
            c4.metric("Users' return", "n/a" if farmer_return is None else f"{farmer_return:.0%}", "so far", delta_color="off")
        lines = all_lines[all_lines["year"] <= years[t - 1]]
        revealed = markers[markers["year"].astype(int) <= years[t - 1]]
        users_chart.altair_chart(_timeline(lines, band, revealed, "adopters", "Farms", x_domain, limits["adopters"]), width="stretch")
        revenue_chart.altair_chart(_timeline(lines, band, revealed, "revenue", "R$ millions", x_domain, limits["revenue"], scale=1e6),
                                   width="stretch")
        with map_box.container():
            bubble_map(pd.Series(story_a.saves_by_season[:t].sum(axis=0), index=market.municipalities), points, names, (192, 57, 43))
        table = sa[["year", "fire_label", "farmer_price", "adopters", "new", "stopped", "fires_held", "revenue"]].rename(columns={
            "year": "Season", "fire_label": "Fire", "farmer_price": "Farmer pays", "adopters": "Users", "new": "New",
            "stopped": "Stopped", "fires_held": "Fires held", "revenue": "Revenue"})
        table_box.dataframe(table, hide_index=True, width="stretch", column_config={
            "Season": st.column_config.NumberColumn(format="%d"),
            "Farmer pays": st.column_config.NumberColumn(format="R$%d"),
            "Revenue": st.column_config.NumberColumn(format="localized")})

    def announce(i: int):
        entry = story_a.log[i]
        for note in entry["notes"]:
            st.toast(f"{entry['year']}: {note}")
        if entry["fire"].startswith("Severe"):
            st.toast(f"{entry['year']}: severe fire season", icon="🔥")

    if autoplay:
        for i in range(shown):
            draw_card(i)
        for t in range(shown + 1, n + 1):
            draw_strip(t)
            draw_card(t - 1)
            draw_panel(t)
            announce(t - 1)
            st.session_state["scenario_shown"] = t
            if t < n:
                time.sleep(AUTO_PACE)
        st.session_state["scenario_autoplay"] = False
        st.rerun()  # redraw once more so the controls match the finished story

    draw_strip(shown)
    for i in range(shown):
        draw_card(i)
    draw_panel(shown)
    if st.session_state.pop("scenario_revealed", False):
        announce(shown - 1)
    if shown < n and mode == "Step by step":
        bottom.button(f"Next season ▶ ({years[shown]})", type="primary", on_click=_advance, args=(n,), key="scenario-next-bottom")
    elif shown == n:
        bottom.success("End of the story. Press **Restart** to play it again, or change the plan or the world.")


def _advance(n: int):
    st.session_state["scenario_shown"] = min(n, st.session_state["scenario_shown"] + 1)
    st.session_state["scenario_revealed"] = True


def _autoplay():
    st.session_state["scenario_autoplay"] = True


def _restart():
    st.session_state.update(scenario_shown=0, scenario_autoplay=False, scenario_revealed=False)


def _fire_icon(label: str) -> str:
    return FIRE_ICONS[label.split()[0]]


def _shock_of(note: str) -> str | None:
    starts = {"State prevention subsidy": "subsidy", "Regulator suspends": "restriction", "A cheaper rival": "competitor",
              "Drought": "drought", "Product qualifies": "tax_relief"}
    return next((shock for prefix, shock in starts.items() if note.startswith(prefix)), None)


def _card_text(entry: dict, row: pd.Series, names: pd.Series, b_seasons: pd.DataFrame | None, money_m) -> str:
    """One season's timeline card: what happened, the fires held, users and revenue."""
    lines = [f"**{entry['year']} · {_fire_icon(row['fire_label'])} {entry['fire']}**", ""]
    for note in entry["notes"]:
        icon = SHOCK_ICONS.get(_shock_of(note), "🔧" if note.startswith("Plan change") else "•")
        lines.append(f"- {icon} {note}")
    if entry["fires_held"]:
        where = ", ".join(f"{names.get(code, code)} {count}" for code, count in entry["saves"])
        lines.append(f"- 🛡️ {entry['fires_held']} treated farm{'s' if entry['fires_held'] > 1 else ''} held a fire line"
                     + (f": {where}" if where else ""))
    change = f"{entry['new']:+d} new, {-entry['stopped'] if entry['stopped'] else 0} stopped"
    if entry["lost_to_rival"]:
        change += f", {entry['lost_to_rival']} lost to the rival"
    lines.append(f"- 👥 {entry['adopters']:,} users ({change}) · revenue {money_m(row['revenue'])}")
    if b_seasons is not None:
        lines.append(f"- Alternative plan: {b_seasons.loc[entry['year'], 'adopters']:,} users")
    return "\n".join(lines)

@st.cache_resource
def _fire_rates(_market, _data):
    return FireRates(_market, _data)
