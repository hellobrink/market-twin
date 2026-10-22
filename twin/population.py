"""Build a synthetic farm population for one state and run the ROI model on every farm.

Reads the processed tables written by `twin.data.build`. Each census cell
(municipality x activity x farm-size group) becomes that many synthetic farms,
and each farm gets:

- an area inside its size group, drawn so the cell's mean area matches the
  census, with suppressed areas estimated by `impute_suppressed_areas`
- a truck or not, drawn from the share of farms of that size in that
  municipality that own one
- a segment, from the rules in `assign_segments`
- fire risk from its municipality's MapBiomas burn rate for its land cover, in the
  chosen fire scenario (see `add_risk`)
- for sugarcane farms, a value at risk from the municipality's PAM production
  value per hectare

Everything else the ROI model needs comes from the segment's base values in the
assumptions file.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from twin.assumptions import Assumptions
from twin.data.codes import ACTIVITIES, ACTIVITY_TOTAL, AREA_GROUP_TOTAL, AREA_GROUPS
from twin.roi import INPUTS, farm_roi

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"

# Segment rules. Farms that match none are outside the modelled market.
SMALL_FARM_HA = (5, 100)  # crop farms in this range: smallholder_ground with a truck, smallholder_drone without
LARGE_CANE_MIN_HA = 100  # temporary-crop farms this size or larger, if their draw says sugarcane
RANCH_MIN_HA = 500  # livestock farms this size or larger
CROP_ACTIVITIES = {"temporary_crops", "permanent_crops", "horticulture"}

# Which MapBiomas land cover sets each segment's fire risk. Smallholders use the
# rate for crops other than cane and pasture.
SEGMENT_COVER = {
    "sugarcane_ground": "cane",
    "remote_ranch_drone": "pasture",
    "smallholder_ground": "other_farmland",
    "smallholder_drone": "other_farmland",
}
BURN_COVERS = ["cane", "pasture", "other_farmland"]
BURN_RATE_PRIOR_HA = 1_000


@dataclass(frozen=True)
class StateData:
    municipalities: pd.DataFrame
    cells: pd.DataFrame
    trucks: pd.DataFrame
    crops: pd.DataFrame
    hotspots: pd.DataFrame
    info: dict
    burned: pd.DataFrame | None = None
    land_cover: pd.DataFrame | None = None

    @classmethod
    def load(cls, state: str = "SP", directory: Path | None = None) -> "StateData":
        d = Path(directory) if directory else PROCESSED / state.lower()
        return cls(
            municipalities=pd.read_csv(d / "municipalities.csv"),
            cells=pd.read_csv(d / "census_cells.csv"),
            trucks=pd.read_csv(d / "trucks.csv"),
            crops=pd.read_csv(d / "crops.csv"),
            hotspots=pd.read_csv(d / "hotspots.csv"),
            info=json.loads((d / "build_info.json").read_text()) if (d / "build_info.json").exists() else {},
            burned=pd.read_csv(d / "burned_area.csv") if (d / "burned_area.csv").exists() else None,
            land_cover=pd.read_csv(d / "land_cover.csv") if (d / "land_cover.csv").exists() else None,
        )


def sample_areas(rng: np.random.Generator, n: int, low: float, high: float | None, total_area: float) -> np.ndarray:
    """n farm areas in [low, high) whose expected mean is the census mean, where that mean fits the group.

    Draws low + (high - low) * U**a, which has mean low + (high - low) / (a + 1), so `a`
    can be solved to hit any mean inside the group. Farm sizes skew small, and this
    reaches means in the bottom of a group that a triangular distribution can't.
    The open top group (no `high`) gets the census mean for every farm.
    """
    mean = total_area / n if n and total_area > 0 else np.nan
    if high is None:
        return np.full(n, mean if np.isfinite(mean) else low * 2)
    if not (np.isfinite(mean) and low <= mean < high):
        mean = (low + high) / 2  # census area suppressed or inconsistent: assume the middle of the group
    position = np.clip((mean - low) / (high - low), 0.01, 0.99)
    return low + (high - low) * rng.random(n) ** (1 / position - 1)


def impute_suppressed_areas(cells: pd.DataFrame) -> pd.DataFrame:
    """Fill area where IBGE suppressed it but still published the farm count.

    For each municipality and activity, the published total area minus the area of
    the size groups that were published is the area of the suppressed groups. That
    remainder is shared across them in proportion to farm count x group midpoint, and
    kept inside each group's bounds. Where the total is suppressed too, area stays
    missing and `sample_areas` assumes the middle of the group.
    """
    cells = cells.copy()
    key = ["municipality", "activity"]
    totals = cells[cells["area_group"] == AREA_GROUP_TOTAL].set_index(key)["area_ha"]
    groups = cells["area_group"].isin(AREA_GROUPS)
    low = cells["area_group"].map(lambda g: AREA_GROUPS.get(g, (np.nan, None))[0])
    high = cells["area_group"].map(lambda g: AREA_GROUPS.get(g, (np.nan, None))[1]).astype(float)
    midpoint = ((low + high) / 2).fillna(low * 2)  # the open top group has no high: use twice its low

    known = cells[groups].groupby(key)["area_ha"].sum(min_count=1).reindex(totals.index).fillna(0)
    remainder = (totals - known).clip(lower=0)
    suppressed = groups & cells["area_ha"].isna() & (cells["establishments"] > 0)
    weight = (cells["establishments"] * midpoint).where(suppressed)
    weight_sum = weight.groupby([cells["municipality"], cells["activity"]]).transform("sum")
    pair = pd.MultiIndex.from_frame(cells[key])
    share = weight / weight_sum * remainder.reindex(pair).to_numpy()
    lower, upper = cells["establishments"] * low, cells["establishments"] * high
    estimate = share.clip(lower=lower, upper=upper.fillna(np.inf))
    cells["area_imputed"] = suppressed & estimate.notna()
    cells.loc[cells["area_imputed"], "area_ha"] = estimate[cells["area_imputed"]]
    return cells


def truck_share(data: StateData) -> pd.DataFrame:
    """Share of farms owning a truck, by municipality and size group, falling back to the state share for that size."""
    totals = data.cells[data.cells["activity"] == ACTIVITY_TOTAL][["municipality", "area_group", "establishments"]]
    merged = totals.merge(data.trucks, on=["municipality", "area_group"], how="left")
    by_group = merged.groupby("area_group")[["establishments_with_trucks", "establishments"]].sum()
    state_share = (by_group["establishments_with_trucks"] / by_group["establishments"]).clip(0, 1)
    share = merged["establishments_with_trucks"] / merged["establishments"]
    merged["truck_share"] = share.where(np.isfinite(share), merged["area_group"].map(state_share)).clip(0, 1)
    return merged[["municipality", "area_group", "truck_share"]]


def cane_share(data: StateData) -> pd.Series:
    """Sugarcane's share of planted crop area by municipality (0 where there is none)."""
    c = data.crops.set_index("municipality")
    return (c["cane_planted_ha"] / c["all_crops_planted_ha"]).replace([np.inf, -np.inf], np.nan).fillna(0).clip(0, 1)


def assign_segments(farms: pd.DataFrame, cane_draw: np.ndarray) -> pd.Series:
    small_lo, small_hi = SMALL_FARM_HA
    small_crop = farms["activity"].isin(CROP_ACTIVITIES) & (farms["area_ha"] >= small_lo) & (farms["area_ha"] < small_hi)
    large_cane = (
        (farms["activity"] == "temporary_crops")
        & (farms["area_ha"] >= LARGE_CANE_MIN_HA)
        & (cane_draw < farms["cane_share"])
    )
    ranch = (farms["activity"] == "livestock") & (farms["area_ha"] >= RANCH_MIN_HA)

    segment = pd.Series(None, index=farms.index, dtype=object)
    segment[small_crop & farms["has_truck"]] = "smallholder_ground"
    segment[small_crop & ~farms["has_truck"]] = "smallholder_drone"
    segment[large_cane] = "sugarcane_ground"
    segment[ranch] = "remote_ranch_drone"
    return segment


def build_population(data: StateData, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cells = impute_suppressed_areas(data.cells)
    cells = cells[
        cells["activity"].isin(ACTIVITIES)
        & cells["area_group"].isin(AREA_GROUPS)
        & (cells["establishments"] > 0)
    ]
    counts = cells["establishments"].astype(int).to_numpy()
    areas = [
        sample_areas(rng, n, *AREA_GROUPS[group], total)
        for n, group, total in zip(counts, cells["area_group"], cells["area_ha"])
    ]
    farms = pd.DataFrame({
        "municipality": np.repeat(cells["municipality"].to_numpy(), counts),
        "activity": np.repeat(cells["activity"].map(ACTIVITIES).to_numpy(), counts),
        "area_group": np.repeat(cells["area_group"].to_numpy(), counts),
        "area_ha": np.concatenate(areas),
    })
    farms = farms.merge(truck_share(data), on=["municipality", "area_group"], how="left")
    farms["has_truck"] = rng.random(len(farms)) < farms["truck_share"].fillna(0)
    farms["cane_share"] = farms["municipality"].map(cane_share(data)).fillna(0)
    farms["segment"] = assign_segments(farms, rng.random(len(farms)))
    return farms


def hotspot_rate(data: StateData, year: int | None = None) -> pd.Series:
    """Reference-satellite hotspots per hectare of farmland, by municipality: the annual mean, or one year's."""
    farmland = data.cells[(data.cells["activity"] == ACTIVITY_TOTAL) & (data.cells["area_group"] == AREA_GROUP_TOTAL)]
    farmland = farmland.set_index("municipality")["area_ha"]
    spots = data.hotspots if year is None else data.hotspots[data.hotspots["year"] == year]
    hotspots = spots.groupby("municipality")["hotspots"].mean()
    rate = (hotspots / farmland).replace([np.inf, -np.inf], np.nan)
    state_rate = hotspots.sum() / farmland.sum()
    return rate.fillna(state_rate)


def sugarcane_value_per_ha(data: StateData) -> pd.Series:
    """PAM production value per harvested hectare of sugarcane, by municipality, falling back to the state average."""
    c = data.crops.set_index("municipality")
    value = (c["cane_value_brl"] / c["cane_harvested_ha"]).replace([np.inf, -np.inf], np.nan)
    return value.fillna(c["cane_value_brl"].sum() / c["cane_harvested_ha"].sum())


def burn_rates(data: StateData, first: int, last: int, prior_ha: float = BURN_RATE_PRIOR_HA) -> pd.DataFrame:
    """Share of each land cover that burns in a year, by municipality, averaged over first..last.

    Burned area comes from MapBiomas Fogo, land area from MapBiomas land cover. Where a
    municipality has little of a land cover, a few burned hectares would give a wild
    rate, so each rate is pulled towards the state rate as if `prior_ha` more hectares
    had burned at the state rate.
    """
    if data.burned is None or data.land_cover is None:
        raise ValueError("burned_area.csv and land_cover.csv are needed; run `python -m twin.data.build` first")
    years = data.burned["year"].between(first, last)
    if not years.any():
        raise ValueError(f"no MapBiomas burned area for {first}-{last}")
    cols = [f"{c}_ha" for c in BURN_COVERS]
    burned = data.burned[years].groupby("municipality")[cols].mean()
    land = data.land_cover.set_index("municipality")[cols]
    burned = burned.reindex(land.index, fill_value=0)
    state = burned.sum() / land.sum()
    rate = (burned + prior_ha * state) / (land + prior_ha)
    return rate.clip(0, 1).rename(columns=dict(zip(cols, BURN_COVERS)))


def scenario_burn_rates(data: StateData, assumptions: Assumptions, scenario: str) -> pd.DataFrame:
    """Burn rates for a fire scenario: one span of years, or a weighted mix of year-based scenarios."""
    fire = assumptions.fire_scenarios[scenario]
    if not fire.mix:
        return burn_rates(data, fire.first, fire.last)
    parts = [share * scenario_burn_rates(data, assumptions, name) for name, share in fire.mix.items()]
    return sum(parts[1:], parts[0])


def hotspot_cross_check(data: StateData, first: int, last: int) -> float:
    """Rank correlation across municipalities between hotspots and burned area, both per hectare of MapBiomas farmland.

    Ranks, because a handful of urban municipalities with almost no farmland have
    extreme rates that would swamp an ordinary correlation.
    """
    years = range(first, last + 1)
    cols = [f"{c}_ha" for c in BURN_COVERS]
    farmland = data.land_cover.set_index("municipality")[cols].sum(axis=1)
    spots = data.hotspots[data.hotspots["year"].isin(years)].groupby("municipality")["hotspots"].mean()
    burned = data.burned[data.burned["year"].isin(years)].groupby("municipality")[cols].mean().sum(axis=1)
    both = pd.DataFrame({"hotspots": spots / farmland, "burned": burned / farmland}).replace([np.inf, -np.inf], np.nan).dropna()
    return float(both["hotspots"].rank().corr(both["burned"].rank()))


def add_risk(farms: pd.DataFrame, data: StateData, assumptions: Assumptions, scenario: str) -> pd.DataFrame:
    """Add each farm's fire risk under a fire scenario and, for sugarcane farms, value at risk per hectare.

    A farm's expected burned share in a year is its municipality's burn rate for the
    farm's land cover. The ROI model splits that into a chance of fire and a share
    burned when fire comes: the share is the segment's base value, and the chance is
    burn rate / share. Where the burn rate is above the share, the chance is capped
    at 1 and the share rises to the burn rate.
    """
    rates = scenario_burn_rates(data, assumptions, scenario).stack()
    cover = farms["segment"].map(SEGMENT_COVER)
    rate = pd.Series(rates.reindex(pd.MultiIndex.from_arrays([farms["municipality"], cover])).to_numpy(), index=farms.index)
    share = farms["segment"].map({k: s.params["burned_area_if_fire_share"].base for k, s in assumptions.segments.items()})
    chance = (rate / share).clip(upper=1)
    cane_value = farms["municipality"].map(sugarcane_value_per_ha(data))
    loss_share = assumptions.population["sugarcane_fire_loss_share"].base
    return farms.assign(
        burn_rate=rate,
        annual_fire_probability=chance,
        burned_area_if_fire_share=(rate / chance).where(chance > 0, share),
        value_at_risk_per_ha=(cane_value * loss_share).where(farms["segment"] == "sugarcane_ground"),
    )


def evaluate(farms: pd.DataFrame, assumptions: Assumptions, strategy: str) -> pd.DataFrame:
    """Run the ROI model on every farm in the modelled market, using segment base values for anything the data doesn't give."""
    farms = farms.dropna(subset=["segment"])
    segment = farms["segment"]
    inputs = {}
    for name in (*INPUTS, "roi_hurdle"):
        base = {key: assumptions.inputs_for(key, strategy)[name].base for key in assumptions.segments}
        inputs[name] = segment.map(base).to_numpy(float)
    inputs["farm_area_ha"] = farms["area_ha"].to_numpy()
    inputs["annual_fire_probability"] = farms["annual_fire_probability"].to_numpy()
    inputs["burned_area_if_fire_share"] = farms["burned_area_if_fire_share"].to_numpy()
    from_data = farms["value_at_risk_per_ha"].to_numpy(float)
    inputs["value_at_risk_per_ha"] = np.where(np.isfinite(from_data), from_data, inputs["value_at_risk_per_ha"])

    out = pd.DataFrame(farm_roi(inputs), index=farms.index)
    out["product_spend"] = inputs["applications_per_season"] * out["treated_ha"] * inputs["product_cost_per_ha"]
    out["clears_hurdle"] = out["roi"] > inputs["roi_hurdle"]
    return farms.join(out).assign(value_at_risk_per_ha=inputs["value_at_risk_per_ha"])
