"""Adoption over time: which farms buy, season by season, across Monte Carlo runs.

Each run:

1. Draws every uncertain input once from its range (product price, containment,
   adoption rates and so on), plus each farm's own ROI hurdle and whether it
   belongs to a cooperative.
2. Steps through the seasons. Before each season, a farm judges its ROI on its
   perceived fire risk, which sits between its municipality's normal-year and
   severe-year burn rates. A severe season resets perceived risk to the severe
   rate, and it then fades with the risk-memory half-life.
3. Farms whose perceived ROI clears their hurdle adopt with the Bass chance
   1 - (1 - p) * (1 - q * peer share). A cooperative member's peers are the other
   members in its municipality. A non-member's peers are the whole municipality,
   weighted down by `non_member_peer_weight`.
4. Adopters whose perceived ROI falls below their hurdle may stop (churn).
5. After the decisions, the season's fire is drawn: severe with
   `severe_year_probability`, otherwise normal.

ROI is linear in the expected burned share of the farm, so the model computes
each farm's ROI at shares 0 and 1 once per run and interpolates every season.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from twin.assumptions import Assumptions, Range
from twin.population import SEGMENT_COVER, StateData, scenario_burn_rates, sugarcane_value_per_ha
from twin.roi import INPUTS, farm_roi


@dataclass(frozen=True)
class Market:
    """What stays fixed about every farm in the modelled market across runs."""

    segments: list[str]
    segment_index: np.ndarray
    municipalities: np.ndarray  # IBGE code for each municipality index
    municipality_index: np.ndarray
    area_ha: np.ndarray
    rate_normal: np.ndarray
    rate_severe: np.ndarray
    cane_value_per_ha: np.ndarray  # NaN for farms that are not sugarcane

    @property
    def size(self) -> int:
        return len(self.area_ha)


def build_market(farms: pd.DataFrame, data: StateData, assumptions: Assumptions,
                 normal: str = "normal", severe: str = "severe") -> Market:
    farms = farms.dropna(subset=["segment"]).reset_index(drop=True)
    segments = list(assumptions.segments)
    codes, municipality_index = np.unique(farms["municipality"].to_numpy(), return_inverse=True)
    cover = farms["segment"].map(SEGMENT_COVER)
    keys = pd.MultiIndex.from_arrays([farms["municipality"], cover])

    def farm_rates(scenario: str) -> np.ndarray:
        return scenario_burn_rates(data, assumptions, scenario).stack().reindex(keys).to_numpy(float)

    cane_value = farms["municipality"].map(sugarcane_value_per_ha(data)).where(farms["segment"] == "sugarcane_ground")
    return Market(
        segments=segments,
        segment_index=farms["segment"].map({s: i for i, s in enumerate(segments)}).to_numpy(),
        municipalities=codes,
        municipality_index=municipality_index,
        area_ha=farms["area_ha"].to_numpy(float),
        rate_normal=farm_rates(normal),
        rate_severe=farm_rates(severe),
        cane_value_per_ha=cane_value.to_numpy(float),
    )


def draw(rng: np.random.Generator, r: Range, size: int | None = None):
    if r.low == r.high:
        return np.full(size, float(r.base)) if size else float(r.base)
    return rng.triangular(r.low, r.base, r.high, size)


def run_once(market: Market, assumptions: Assumptions, strategy: str, rng: np.random.Generator, peers: bool = True) -> tuple[pd.DataFrame, dict]:
    """One Monte Carlo run. Returns a row per season and segment, and the run's drawn inputs."""
    adoption = assumptions.adoption
    seg = market.segment_index
    n, n_seg, n_muni = market.size, len(market.segments), len(market.municipalities)

    # Inputs drawn once per run and segment. Product-level ranges give every segment the same draw.
    shared: dict[str, float] = {}
    inputs = {}
    for name in INPUTS:
        values = []
        for key in market.segments:
            r = assumptions.inputs_for(key, strategy)[name]
            if name in assumptions.product:
                shared.setdefault(name, draw(rng, r))
                values.append(shared[name])
            else:
                values.append(draw(rng, r))
        inputs[name] = np.asarray(values)[seg]
    inputs["farm_area_ha"] = market.area_ha
    loss_share = draw(rng, assumptions.population["sugarcane_fire_loss_share"])
    inputs["value_at_risk_per_ha"] = np.where(np.isfinite(market.cane_value_per_ha), market.cane_value_per_ha * loss_share, inputs["value_at_risk_per_ha"])
    inputs["annual_fire_probability"] = np.ones(n)

    at_zero = farm_roi({**inputs, "burned_area_if_fire_share": np.zeros(n)})
    at_one = farm_roi({**inputs, "burned_area_if_fire_share": np.ones(n)})
    roi_zero, roi_slope = at_zero["roi"], at_one["roi"] - at_zero["roi"]
    spend = inputs["applications_per_season"] * at_one["treated_ha"] * inputs["product_cost_per_ha"]

    rates = {name: draw(rng, r) for name, r in adoption.rates.items()}
    hurdle = draw(rng, assumptions.buyer["roi_hurdle"], n)
    coop_share = np.array([draw(rng, adoption.coop_member_share[key]) for key in market.segments])
    member = rng.random(n) < coop_share[seg]
    muni = market.municipality_index
    farms_in_muni = np.bincount(muni, minlength=n_muni)
    members_in_muni = np.bincount(muni[member], minlength=n_muni)

    decay = 0.5 ** (1 / rates["risk_memory_half_life"])
    salience = decay ** (adoption.start_year - adoption.last_severe_year)
    adopted = np.zeros(n, dtype=bool)
    rows = []
    severe_seasons = 0
    for season in range(adoption.seasons):
        perceived = market.rate_normal + (market.rate_severe - market.rate_normal) * salience
        willing = roi_zero + roi_slope * perceived >= hurdle

        peer = np.zeros(n)
        if peers:
            muni_share = np.bincount(muni, weights=adopted, minlength=n_muni) / np.maximum(farms_in_muni, 1)
            coop_adopters = np.bincount(muni[member], weights=adopted[member], minlength=n_muni)
            coop_share_adopted = coop_adopters / np.maximum(members_in_muni, 1)
            peer = np.where(member, coop_share_adopted[muni], rates["non_member_peer_weight"] * muni_share[muni])
        chance = 1 - (1 - rates["innovation_rate"]) * (1 - rates["imitation_rate"] * peer)
        new = ~adopted & willing & (rng.random(n) < chance)
        stop = adopted & ~willing & (rng.random(n) < rates["churn_when_unprofitable"])
        adopted = (adopted | new) & ~stop

        severe = rng.random() < rates["severe_year_probability"]
        severe_seasons += severe
        rows.append(pd.DataFrame({
            "season": season + 1,
            "year": adoption.start_year + season,
            "severe": severe,
            "segment": market.segments,
            "adopters": np.bincount(seg, weights=adopted, minlength=n_seg),
            "new": np.bincount(seg, weights=new, minlength=n_seg),
            "willing": np.bincount(seg, weights=willing, minlength=n_seg),
            "revenue": np.bincount(seg, weights=spend * adopted, minlength=n_seg),
        }))
        salience = 1.0 if severe else salience * decay

    drawn = {
        **rates,
        "product_cost_per_ha": shared["product_cost_per_ha"],
        "containment_rate": shared["containment_rate"],
        "sugarcane_fire_loss_share": loss_share,
        "sugarcane_coop_share": coop_share[market.segments.index("sugarcane_ground")],
        "severe_seasons": severe_seasons,
        "final_adopters_by_municipality": np.bincount(muni, weights=adopted, minlength=n_muni),
    }
    return pd.concat(rows, ignore_index=True), drawn


def simulate_adoption(market: Market, assumptions: Assumptions, strategy: str, runs: int | None = None,
                      seed: int = 0, peers: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Many runs. Returns season rows for every run, one row of drawn inputs per run, and mean final adopters by municipality."""
    runs = runs or assumptions.adoption.runs
    rng = np.random.default_rng(seed)
    seasons, draws = [], []
    by_muni = np.zeros(len(market.municipalities))
    for run in range(runs):
        rows, drawn = run_once(market, assumptions, strategy, rng, peers=peers)
        seasons.append(rows.assign(run=run))
        by_muni += drawn.pop("final_adopters_by_municipality")
        draws.append(drawn)
    return pd.concat(seasons, ignore_index=True), pd.DataFrame(draws), by_muni / runs


def yearly_summary(seasons: pd.DataFrame) -> pd.DataFrame:
    """P10, median and P90 across runs of total adopters and revenue per year, plus how many runs have had a severe season so far."""
    totals = seasons.groupby(["run", "year"]).agg(adopters=("adopters", "sum"), revenue=("revenue", "sum"), severe=("severe", "first"))
    totals["severe_so_far"] = totals.groupby(level="run")["severe"].cummax()
    grouped = totals.groupby(level="year")
    out = pd.DataFrame({
        "adopters_p10": grouped["adopters"].quantile(0.1),
        "adopters_median": grouped["adopters"].median(),
        "adopters_p90": grouped["adopters"].quantile(0.9),
        "revenue_p10": grouped["revenue"].quantile(0.1),
        "revenue_median": grouped["revenue"].median(),
        "revenue_p90": grouped["revenue"].quantile(0.9),
        "runs_severe_so_far": grouped["severe_so_far"].mean(),
    })
    return out


def drivers(seasons: pd.DataFrame, draws: pd.DataFrame) -> pd.Series:
    """Rank correlation between each drawn input and final-season adopters, strongest first."""
    final = seasons[seasons["season"] == seasons["season"].max()].groupby("run")["adopters"].sum()
    ranked = draws.rank()
    corr = ranked.apply(lambda col: col.corr(final.rank()))
    return corr.reindex(corr.abs().sort_values(ascending=False).index)
