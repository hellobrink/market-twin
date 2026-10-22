"""Calibrate `fires_per_hotspot` so the synthetic farms burn as much farmland as MapBiomas records.

The population gives each farm an annual fire probability

    p = 1 - exp(-fires_per_hotspot * hotspot_rate * area_ha)

and the ROI model burns `burned_area_if_fire_share` of the farm when a fire arrives.
So the population's expected burned farmland in a year is the sum over farms of
p * burned_share * area. This module finds the `fires_per_hotspot` that makes that
sum equal MapBiomas Fogo's burned farmland (sugarcane, pasture and other crops) for
the state: once for the mean year, and once for each year to give a range.

Only the product of fire probability and burned share is pinned down by burned
area. The calibration holds each segment's base burned share fixed, so if those
shares change, rerun it.

Run from the repo root:

    .venv/bin/python -m twin.calibration
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from twin.assumptions import Assumptions, load
from twin.data.mapbiomas import FARMLAND_GROUPS
from twin.population import CROP_ACTIVITIES, LARGE_CANE_MIN_HA, StateData, build_population, hotspot_rate
from twin.report import DEFAULT_ASSUMPTIONS, pct


def burned_share(farms: pd.DataFrame, assumptions: Assumptions) -> np.ndarray:
    """Burned share for every farm, including those outside the modelled market.

    Segment farms use their segment's base value. Other farms borrow from the
    nearest segment: large crop farms from sugarcane, small crop farms from
    smallholders, livestock farms from ranches.
    """
    base = {key: seg.params["burned_area_if_fire_share"].base for key, seg in assumptions.segments.items()}
    nearest = np.where(
        farms["activity"] == "livestock", "remote_ranch_drone",
        np.where(farms["area_ha"] >= LARGE_CANE_MIN_HA, "sugarcane_ground", "smallholder_drone"),
    )
    segment = farms["segment"].where(farms["segment"].notna(), pd.Series(nearest, index=farms.index))
    return segment.map(base).to_numpy(float)


def expected_burned_ha(k: float, area: np.ndarray, rate: np.ndarray, share: np.ndarray) -> float:
    return float(np.sum((1 - np.exp(-k * rate * area)) * share * area))


def solve_k(area: np.ndarray, rate: np.ndarray, share: np.ndarray, target: float) -> float:
    """The fires_per_hotspot at which expected burned area equals target, found by bisection on a log scale."""
    ceiling = float(np.sum(share[rate > 0] * area[rate > 0]))
    if not 0 < target < ceiling:
        raise ValueError(f"target {target:,.0f} ha is outside what the population can burn (0 to {ceiling:,.0f} ha)")
    low, high = 1e-4, 1e6
    for _ in range(200):
        mid = np.sqrt(low * high)
        if expected_burned_ha(mid, area, rate, share) < target:
            low = mid
        else:
            high = mid
    return float(np.sqrt(low * high))


def farmland_burned(data: StateData) -> pd.DataFrame:
    burned = data.burned.copy()
    burned["farmland_ha"] = burned[[f"{g}_ha" for g in FARMLAND_GROUPS]].sum(axis=1)
    return burned


def calibrate(data: StateData, farms: pd.DataFrame, assumptions: Assumptions) -> dict:
    if data.burned is None:
        raise ValueError("no burned_area.csv for this state; run `python -m twin.data.build` first")
    burned = farmland_burned(data)
    area = farms["area_ha"].to_numpy()
    share = burned_share(farms, assumptions)

    def k_for(year: int | None, target: float) -> float:
        rate = farms["municipality"].map(hotspot_rate(data, year)).to_numpy()
        return solve_k(area, rate, share, target)

    by_year = burned.groupby("year")["farmland_ha"].sum()
    k_mean = k_for(None, by_year.mean())
    k_by_year = pd.Series({year: k_for(year, target) for year, target in by_year.items()}, name="fires_per_hotspot")

    # How well the calibrated model places burned area across municipalities.
    rate = farms["municipality"].map(hotspot_rate(data)).to_numpy()
    predicted = pd.Series((1 - np.exp(-k_mean * rate * area)) * share * area, index=farms.index)
    per_muni = pd.DataFrame({
        "predicted_ha": predicted.groupby(farms["municipality"]).sum(),
        "observed_ha": burned.groupby("municipality")["farmland_ha"].mean(),
    }).fillna(0)
    return {
        "k_mean": k_mean,
        "k_by_year": k_by_year,
        "burned_by_year": by_year,
        "per_municipality": per_muni,
        "correlation": per_muni["predicted_ha"].corr(per_muni["observed_ha"]),
        "rank_correlation": per_muni["predicted_ha"].rank().corr(per_muni["observed_ha"].rank()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default="SP")
    parser.add_argument("--assumptions", default=DEFAULT_ASSUMPTIONS, type=Path)
    parser.add_argument("--seed", default=0, type=int)
    args = parser.parse_args()

    assumptions = load(args.assumptions)
    data = StateData.load(args.state)
    farms = build_population(data, seed=args.seed)
    result = calibrate(data, farms, assumptions)
    hotspots = data.hotspots.groupby("year")["hotspots"].sum()

    print(f"Calibrating fires_per_hotspot for {args.state} against MapBiomas Fogo burned farmland\n")
    print(f"  {'year':<6}{'burned farmland':>18}{'hotspots':>10}{'ha per hotspot':>16}{'fires_per_hotspot':>20}")
    for year, ha in result["burned_by_year"].items():
        print(f"  {year:<6}{ha:>15,.0f} ha{hotspots[year]:>10,}{ha / hotspots[year]:>16.1f}{result['k_by_year'][year]:>20.2f}")
    k_years = result["k_by_year"]
    print(f"\n  Mean year: fires_per_hotspot = {result['k_mean']:.2f}")
    print(f"  Across years: P10 {k_years.quantile(0.1):.2f}, median {k_years.median():.2f}, P90 {k_years.quantile(0.9):.2f}, max {k_years.max():.2f}")
    print(f"  Municipality fit, mean year: correlation {result['correlation']:.2f}, rank correlation {result['rank_correlation']:.2f}")
    worst = result["per_municipality"].assign(gap=lambda m: m["predicted_ha"] - m["observed_ha"])
    names = data.municipalities.set_index("municipality")["name"]
    print("\n  Largest gaps, predicted minus observed (ha a year)")
    for code, row in worst.reindex(worst["gap"].abs().sort_values(ascending=False).index).head(8).iterrows():
        print(f"    {names.get(code, code):<28}{row['predicted_ha']:>10,.0f} predicted{row['observed_ha']:>10,.0f} observed")

    by_size = predicted_by_farm_size(farms, data, assumptions, result["k_mean"])
    print("\n  Where the calibrated model puts burning, by farm size")
    print(f"    {'farm size':<16}{'share of farmland':>20}{'share of burning':>18}{'burned a year':>15}")
    for size, row in by_size.iterrows():
        print(f"    {size:<16}{pct(row['area_share']):>20}{pct(row['burn_share']):>18}{row['burned_pct']:>14.2f}%")
    print("\n  Burned shares are held at segment base values, so rerun this if they change.")


def predicted_by_farm_size(farms: pd.DataFrame, data: StateData, assumptions: Assumptions, k: float) -> pd.DataFrame:
    """Share of farmland, share of predicted burning and burned percentage a year, by farm size band."""
    area = farms["area_ha"].to_numpy()
    rate = farms["municipality"].map(hotspot_rate(data)).to_numpy()
    burn = (1 - np.exp(-k * rate * area)) * burned_share(farms, assumptions) * area
    bands = pd.cut(farms["area_ha"], [0, 20, 100, 500, 2_500, np.inf], labels=["under 20 ha", "20-100 ha", "100-500 ha", "500-2,500 ha", "2,500 ha +"])
    table = pd.DataFrame({"area": area, "burn": burn, "band": bands}).groupby("band", observed=True)[["area", "burn"]].sum()
    return pd.DataFrame({
        "area_share": table["area"] / table["area"].sum(),
        "burn_share": table["burn"] / table["burn"].sum(),
        "burned_pct": table["burn"] / table["area"] * 100,
    })


if __name__ == "__main__":
    main()
