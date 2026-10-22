"""Per-farm return on investment for preventive fire treatment.

`farm_roi` takes floats or numpy arrays, so the same code gives one base case
or thousands of Monte Carlo draws at once.

The model, per farm per dry season:

    treated_ha    = farm_area_ha * treated_share
    cost          = applications_per_season * treated_ha
                    * (product_cost_per_ha + application_cost_per_ha)
    avoided_ha    = annual_fire_probability * burned_area_if_fire_share * farm_area_ha
                    * containment_rate * timing_coverage
    avoided_loss  = avoided_ha * value_at_risk_per_ha
    water_value   = treated_ha * baseline_water_m3_per_ha * water_saving_share
                    * water_cost_per_m3
    roi           = (avoided_loss + water_value - cost) / cost

It assumes treated strips are placed so that stopping a fire at the strip
protects the area that would otherwise burn.
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd

from twin.assumptions import Range

INPUTS = (
    "farm_area_ha",
    "treated_share",
    "applications_per_season",
    "product_cost_per_ha",
    "application_cost_per_ha",
    "annual_fire_probability",
    "burned_area_if_fire_share",
    "containment_rate",
    "timing_coverage",
    "value_at_risk_per_ha",
    "baseline_water_m3_per_ha",
    "water_saving_share",
    "water_cost_per_m3",
)


def farm_roi(p: Mapping) -> dict:
    missing = [name for name in INPUTS if name not in p]
    if missing:
        raise KeyError(f"missing inputs: {', '.join(missing)}")

    treated_ha = p["farm_area_ha"] * p["treated_share"]
    treated_ha_applications = p["applications_per_season"] * treated_ha
    cost = treated_ha_applications * (p["product_cost_per_ha"] + p["application_cost_per_ha"])

    avoided_ha = (
        p["annual_fire_probability"]
        * p["burned_area_if_fire_share"]
        * p["farm_area_ha"]
        * p["containment_rate"]
        * p["timing_coverage"]
    )
    avoided_loss = avoided_ha * p["value_at_risk_per_ha"]
    water_saved_m3 = treated_ha * p["baseline_water_m3_per_ha"] * p["water_saving_share"]
    water_value = water_saved_m3 * p["water_cost_per_m3"]

    benefit = avoided_loss + water_value
    net = benefit - cost
    return {
        "treated_ha": treated_ha,
        "cost": cost,
        "avoided_ha": avoided_ha,
        "avoided_loss": avoided_loss,
        "water_saved_m3": water_saved_m3,
        "water_value": water_value,
        "benefit": benefit,
        "net": net,
        "roi": net / cost,
        # Product price per hectare per application at which benefit equals cost.
        "breakeven_product_cost_per_ha": benefit / treated_ha_applications - p["application_cost_per_ha"],
    }


def base_case(ranges: Mapping[str, Range]) -> dict:
    return farm_roi({name: r.base for name, r in ranges.items()})


def simulate(ranges: Mapping[str, Range], n: int = 10_000, seed: int = 0) -> pd.DataFrame:
    """Sample every range n times and return the draws alongside the outputs."""
    rng = np.random.default_rng(seed)
    draws = {name: _sample(rng, r, n) for name, r in ranges.items()}
    return pd.DataFrame({**draws, **farm_roi(draws)})


def _sample(rng: np.random.Generator, r: Range, n: int) -> np.ndarray:
    if r.low == r.high:
        return np.full(n, float(r.base))
    return rng.triangular(r.low, r.base, r.high, n)


def summarise(sims: pd.DataFrame) -> dict:
    roi = sims["roi"]
    out = {
        "roi_p10": roi.quantile(0.10),
        "roi_median": roi.median(),
        "roi_p90": roi.quantile(0.90),
        "share_profitable": (roi > 0).mean(),
    }
    if "roi_hurdle" in sims:
        out["share_clearing_hurdle"] = (roi > sims["roi_hurdle"]).mean()
    return out


def tornado(ranges: Mapping[str, Range], output: str = "roi") -> pd.DataFrame:
    """Swing each model input from low to high with the rest at base.

    Rows are sorted so the input that moves the output most comes first.
    """
    base_inputs = {name: r.base for name, r in ranges.items()}
    base_value = farm_roi(base_inputs)[output]
    rows = []
    for name in INPUTS:
        r = ranges[name]
        at_low = farm_roi({**base_inputs, name: r.low})[output]
        at_high = farm_roi({**base_inputs, name: r.high})[output]
        rows.append({
            "input": name,
            "status": r.status,
            "at_low": at_low,
            "at_high": at_high,
            "swing": abs(at_high - at_low),
            "base": base_value,
        })
    return pd.DataFrame(rows).sort_values("swing", ascending=False, ignore_index=True)
