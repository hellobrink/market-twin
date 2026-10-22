"""Scenario mode: one storyline, season by season, under a plan the team controls and a world it doesn't.

A **plan** sets the team's levers for each season: price, treatment strategy,
sales effort, whether a cooperative partnership runs, and which segments are
sold to. A **world** sets what happens to them: each season's fire (normal,
severe, or a real year from 2015-2024) and shocks such as a subsidy, a sales
suspension, a rival product, a drought or tax relief.

`play` runs one plan through one world. It follows the adoption model in
`twin.adoption`, plus three things a storyline needs:

- each adopter's farm either meets a fire or doesn't, and a treated farm that
  holds its fire line becomes a story its neighbours hear (`testimonial_weight`)
- the shocks change the price farmers pay, NoFire's ability to sell, or churn
- perceived fire risk follows the actual seasons: it rises to at least what
  the latest season burned and fades with the risk-memory half-life

Randomness comes from fixed streams keyed by `farm_seed`, so two plans played
through the same world with the same seed differ only because of the plan.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from twin.adoption import Market, draw, segment_inputs
from twin.assumptions import SHOCKS, Assumptions
from twin.population import SEGMENT_COVER, StateData, burn_rates
from twin.roi import farm_roi

SHOCK_TEXT = {
    "subsidy": "State prevention subsidy starts",
    "restriction": "Regulator suspends retardant sales this season",
    "competitor": "A cheaper rival product arrives",
    "drought": "Drought makes water scarce",
    "tax_relief": "Product qualifies for reduced agricultural input tax",
}


@dataclass(frozen=True)
class SeasonPlan:
    price: float
    strategy: str
    sales_effort: float = 1.0
    coop_partnership: bool = False


@dataclass(frozen=True)
class Plan:
    seasons: tuple[SeasonPlan, ...]
    segments: frozenset[str]

    @classmethod
    def constant(cls, n: int, price: float, strategy: str, segments, sales_effort: float = 1.0, coop_partnership: bool = False) -> "Plan":
        return cls(tuple(SeasonPlan(price, strategy, sales_effort, coop_partnership) for _ in range(n)), frozenset(segments))


@dataclass(frozen=True)
class Season:
    fire: str  # "normal", "severe", or a year with MapBiomas data such as "2017"
    shocks: frozenset[str] = frozenset()


@dataclass(frozen=True)
class World:
    start_year: int
    seasons: tuple[Season, ...]
    seasons_since_severe: int | None  # before the first season; None means long ago
    label: str


def random_world(assumptions: Assumptions, preset: str, n: int, seed: int, start_year: int,
                 seasons_since_severe: int | None) -> World:
    """Events drawn at a preset's chances. A rival and tax relief each arrive at most once."""
    chances = assumptions.scenario.presets[preset]
    rng = np.random.default_rng(seed)
    seasons, arrived = [], set()
    for _ in range(n):
        fire = "severe" if rng.random() < chances["severe"] else "normal"
        shocks = {s for s in SHOCKS if rng.random() < chances[s]}  # one draw per shock keeps streams aligned
        for once in ("competitor", "tax_relief"):
            if once in shocks:
                if once in arrived:
                    shocks.discard(once)
                arrived.add(once)
        seasons.append(Season(fire, frozenset(shocks)))
    return World(start_year, tuple(seasons), seasons_since_severe, f"{preset} world #{seed}")


def replay_world(first: int = 2015, last: int = 2024, seasons_since_severe: int | None = None) -> World:
    """The real fire seasons of first..last, with no shocks."""
    return World(first, tuple(Season(str(y)) for y in range(first, last + 1)), seasons_since_severe, f"replay {first}-{last}")


class FireRates:
    """Each farm's burn rate for a season's fire: the normal or severe scenario, or one real year."""

    def __init__(self, market: Market, data: StateData):
        self.market, self.data = market, data
        self._cache = {"normal": market.rate_normal, "severe": market.rate_severe}

    def __call__(self, fire: str) -> np.ndarray:
        if fire not in self._cache:
            year = int(fire)
            m = self.market
            codes = m.municipalities[m.municipality_index]
            cover = np.asarray([SEGMENT_COVER[s] for s in m.segments])[m.segment_index]
            rates = burn_rates(self.data, year, year).stack()
            self._cache[fire] = rates.reindex(pd.MultiIndex.from_arrays([codes, cover])).to_numpy(float)
        return self._cache[fire]


@dataclass
class Story:
    seasons: pd.DataFrame
    log: list[dict]
    saves_by_municipality: np.ndarray  # fires held over the whole run
    saves_by_season: np.ndarray  # seasons x municipalities, for revealing a story season by season


def fire_label(ratio: float) -> str:
    if ratio >= 2:
        return "Severe fire season"
    if ratio >= 1.3:
        return "Bad fire season"
    if ratio <= 0.7:
        return "Quiet fire season"
    return "Normal fire season"


def play(market: Market, fire_rates: FireRates, assumptions: Assumptions, plan: Plan, world: World,
         farm_seed: int = 0, uncertain: str = "base") -> Story:
    """Play one plan through one world. `uncertain` is "base" for base values or "drawn" to draw each range."""
    n, n_muni, n_seasons = market.size, len(market.municipalities), len(world.seasons)
    if len(plan.seasons) != n_seasons:
        raise ValueError(f"plan has {len(plan.seasons)} seasons but the world has {n_seasons}")
    seg, muni = market.segment_index, market.municipality_index
    events = assumptions.scenario.events

    farm_rng = np.random.default_rng([farm_seed, 1])
    pick = (lambda r: draw(farm_rng, r)) if uncertain == "drawn" else (lambda r: r.base)
    rates = {k: pick(r) for k, r in assumptions.adoption.rates.items()}
    story = {k: pick(r) for k, r in assumptions.scenario.rates.items()}
    loss_share = pick(assumptions.population["sugarcane_fire_loss_share"])
    hurdle = draw(farm_rng, assumptions.buyer["roi_hurdle"], n)  # farms always differ in what they need
    coop_share = np.array([pick(assumptions.adoption.coop_member_share[k]) for k in market.segments])
    member = farm_rng.random(n) < coop_share[seg]
    burned_share = np.array([assumptions.segments[k].params["burned_area_if_fire_share"].base for k in market.segments])[seg]

    shared: dict[str, float] = {}
    by_strategy = {}
    for i, strategy in enumerate(assumptions.strategies):
        rng = np.random.default_rng([farm_seed, 2, i]) if uncertain == "drawn" else None
        inputs = segment_inputs(market, assumptions, strategy, rng, shared)
        inputs["farm_area_ha"] = market.area_ha
        inputs["value_at_risk_per_ha"] = np.where(np.isfinite(market.cane_value_per_ha),
                                                  market.cane_value_per_ha * loss_share, inputs["value_at_risk_per_ha"])
        inputs["annual_fire_probability"] = np.ones(n)
        by_strategy[strategy] = inputs

    # Common random numbers: every plan played with this seed sees the same draws.
    dice = np.random.default_rng([farm_seed, 3])
    roll = {k: dice.random((n_seasons, n)) for k in ("adopt", "churn", "hit", "cover", "contain", "rival")}

    targeted = np.isin(seg, [market.segments.index(s) for s in plan.segments])
    farms_in_muni = np.maximum(np.bincount(muni, minlength=n_muni), 1)
    members_in_muni = np.maximum(np.bincount(muni[member], minlength=n_muni), 1)
    is_cane = seg == market.segments.index("sugarcane_ground")
    decay = 0.5 ** (1 / rates["risk_memory_half_life"])
    story_decay = 0.5 ** (1 / story["testimonial_memory"])
    gap = 99 if world.seasons_since_severe is None else world.seasons_since_severe
    perceived = market.rate_normal + (market.rate_severe - market.rate_normal) * decay ** gap

    adopted = np.zeros(n, dtype=bool)
    testimonials = np.zeros(n_muni)
    saves_by_muni = np.zeros(n_muni)
    saves_by_season = []
    subsidy_left, rival, relief = 0, False, False
    rows, log, previous = [], [], None
    for t, (season, sp) in enumerate(zip(world.seasons, plan.seasons)):
        year = world.start_year + t
        notes = []
        if "subsidy" in season.shocks:
            subsidy_left = int(events["subsidy"]["seasons"])
            notes.append(f"{SHOCK_TEXT['subsidy']}: farmers pay {events['subsidy']['share']:.0%} less for {subsidy_left} seasons")
        if "competitor" in season.shocks and not rival:
            rival = True
            notes.append(f"{SHOCK_TEXT['competitor']}: it wins {events['competitor']['capture']:.0%} of new buyers from now on")
        if "tax_relief" in season.shocks and not relief:
            relief = True
            notes.append(f"{SHOCK_TEXT['tax_relief']}: farmers pay {events['tax_relief']['share']:.0%} less from now on")
        restricted = "restriction" in season.shocks
        drought = "drought" in season.shocks
        if restricted:
            notes.append(SHOCK_TEXT["restriction"])
        if drought:
            notes.append(f"{SHOCK_TEXT['drought']}: water costs {events['drought']['water_cost_multiplier']:g}x")
        if previous and sp != previous:
            changes = []
            if sp.price != previous.price:
                changes.append(f"price R${previous.price:,.0f} to R${sp.price:,.0f}")
            if sp.strategy != previous.strategy:
                changes.append(f"strategy {previous.strategy} to {sp.strategy}")
            if sp.sales_effort != previous.sales_effort:
                changes.append(f"sales effort {previous.sales_effort:g}x to {sp.sales_effort:g}x")
            if sp.coop_partnership != previous.coop_partnership:
                changes.append("cooperative partnership " + ("starts" if sp.coop_partnership else "ends"))
            notes.append("Plan change: " + ", ".join(changes))
        previous = sp

        farmer_price = sp.price
        if subsidy_left > 0:
            farmer_price *= 1 - events["subsidy"]["share"]
        if relief:
            farmer_price *= 1 - events["tax_relief"]["share"]
        inputs = dict(by_strategy[sp.strategy])
        inputs["product_cost_per_ha"] = np.full(n, farmer_price)
        if drought:
            inputs["water_cost_per_m3"] = inputs["water_cost_per_m3"] * events["drought"]["water_cost_multiplier"]
        at_zero = farm_roi({**inputs, "burned_area_if_fire_share": np.zeros(n)})
        at_one = farm_roi({**inputs, "burned_area_if_fire_share": np.ones(n)})
        perceived_roi = at_zero["roi"] + (at_one["roi"] - at_zero["roi"]) * perceived
        willing = targeted & (perceived_roi >= hurdle)

        # Peers: adopters plus recent contained-fire stories, among cooperative members or the whole municipality.
        muni_peer = np.minimum(1, (np.bincount(muni, weights=adopted, minlength=n_muni) + testimonials) / farms_in_muni)
        coop_peer = np.minimum(1, (np.bincount(muni[member], weights=adopted[member], minlength=n_muni) + testimonials) / members_in_muni)
        imitation = rates["imitation_rate"] * np.where(member & sp.coop_partnership, story["partnership_boost"], 1.0)
        peer_pull = np.where(member, imitation * coop_peer[muni], imitation * rates["non_member_peer_weight"] * muni_peer[muni])
        chance = 1 - (1 - min(1.0, rates["innovation_rate"] * sp.sales_effort)) * (1 - np.minimum(1, peer_pull))
        new = np.zeros(n, dtype=bool) if restricted else (~adopted & willing & (roll["adopt"][t] < chance))
        lost_to_rival = new & rival & (roll["rival"][t] < events["competitor"]["capture"])
        new &= ~lost_to_rival
        churn = np.where(willing, 0.0, rates["churn_when_unprofitable"]) + (events["competitor"]["churn"] if rival else 0.0)
        stopped = adopted & (roll["churn"][t] < churn)
        adopted = (adopted | new) & ~stopped

        # The season's fire.
        actual = fire_rates(season.fire)
        treating = adopted & (not restricted)
        hit_chance = np.minimum(1, actual / burned_share)
        hit = roll["hit"][t] < hit_chance
        held = treating & hit & (roll["cover"][t] < inputs["timing_coverage"]) & (roll["contain"][t] < inputs["containment_rate"])
        burned_if_hit = np.where(hit_chance > 0, actual / np.maximum(hit_chance, 1e-12), 0) * market.area_ha
        avoided = np.where(held, burned_if_hit * inputs["value_at_risk_per_ha"], 0)
        farmer_cost = np.where(treating, at_one["cost"], 0)
        water = np.where(treating, at_one["water_value"], 0)
        revenue = np.where(treating, inputs["applications_per_season"] * at_one["treated_ha"] * sp.price, 0)
        saves = np.bincount(muni, weights=held, minlength=n_muni)
        saves_by_muni += saves
        saves_by_season.append(saves)
        testimonials = testimonials * story_decay + story["testimonial_weight"] * saves
        ratio = actual[is_cane].mean() / market.rate_normal[is_cane].mean()

        spend = farmer_cost.sum()
        rows.append({
            "year": year,
            "fire": season.fire,
            "fire_label": fire_label(ratio),
            "fire_ratio": ratio,
            "shocks": ", ".join(sorted(season.shocks)),
            "price": sp.price,
            "farmer_price": farmer_price,
            "strategy": sp.strategy,
            "adopters": int(adopted.sum()),
            "new": int(new.sum()),
            "stopped": int(stopped.sum()),
            "lost_to_rival": int(lost_to_rival.sum()),
            "willing": int(willing.sum()),
            "revenue": revenue.sum(),
            "fires_held": int(held.sum()),
            "avoided_loss": avoided.sum(),
            "farmer_spend": spend,
            "water_value": water.sum(),
            "adopter_return": (avoided.sum() + water.sum() - spend) / spend if spend > 0 else np.nan,
            "perceived_vs_normal": perceived[is_cane].mean() / market.rate_normal[is_cane].mean(),
        })
        top = np.argsort(saves)[::-1][:3]
        log.append({
            "year": year,
            "fire": fire_label(ratio) + (f" (cane burned {ratio:.1f}x the normal-year rate)" if ratio >= 1.3 or ratio <= 0.7 else ""),
            "notes": notes,
            "saves": [(market.municipalities[i], int(saves[i])) for i in top if saves[i] > 0],
            "fires_held": int(held.sum()),
            "adopters": int(adopted.sum()),
            "new": int(new.sum()),
            "stopped": int(stopped.sum()),
            "lost_to_rival": int(lost_to_rival.sum()),
        })

        subsidy_left = max(0, subsidy_left - 1)
        perceived = np.maximum(market.rate_normal + (perceived - market.rate_normal) * decay, actual)

    return Story(pd.DataFrame(rows), log, saves_by_muni, np.array(saves_by_season))


def play_range(market: Market, fire_rates: FireRates, assumptions: Assumptions, plan: Plan, world_for_run, runs: int,
               seed: int = 0) -> pd.DataFrame:
    """Many plays of one plan with uncertain inputs drawn each run. `world_for_run(i)` gives run i's world.

    Returns P10, median and P90 of adopters and revenue for each season.
    """
    results = []
    for i in range(runs):
        s = play(market, fire_rates, assumptions, plan, world_for_run(i), farm_seed=seed * 100_000 + i, uncertain="drawn").seasons
        results.append(s[["year", "adopters", "revenue", "fires_held"]].assign(run=i))
    df = pd.concat(results, ignore_index=True)
    g = df.groupby("year")
    return pd.DataFrame({
        "adopters_p10": g["adopters"].quantile(0.1), "adopters_median": g["adopters"].median(), "adopters_p90": g["adopters"].quantile(0.9),
        "revenue_p10": g["revenue"].quantile(0.1), "revenue_median": g["revenue"].median(), "revenue_p90": g["revenue"].quantile(0.9),
    })
