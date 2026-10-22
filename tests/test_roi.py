from pathlib import Path

import pytest

from twin.assumptions import Range, load
from twin.roi import INPUTS, farm_roi, simulate, summarise, tornado

ASSUMPTIONS = Path(__file__).resolve().parent.parent / "assumptions" / "nofire_brazil.yaml"

# Round numbers so the expected outputs can be worked out by hand.
SIMPLE = {
    "farm_area_ha": 100,
    "treated_share": 0.1,
    "applications_per_season": 2,
    "product_cost_per_ha": 400,
    "application_cost_per_ha": 100,
    "annual_fire_probability": 0.2,
    "burned_area_if_fire_share": 0.5,
    "containment_rate": 0.5,
    "timing_coverage": 0.5,
    "value_at_risk_per_ha": 1000,
    "baseline_water_m3_per_ha": 10,
    "water_saving_share": 0.5,
    "water_cost_per_m3": 10,
}


def test_hand_calculation():
    out = farm_roi(SIMPLE)
    assert out["treated_ha"] == pytest.approx(10)
    assert out["cost"] == pytest.approx(10_000)  # 2 applications x 10 ha x R$500
    assert out["avoided_ha"] == pytest.approx(2.5)  # 0.2 x 0.5 x 100 x 0.5 x 0.5
    assert out["avoided_loss"] == pytest.approx(2_500)
    assert out["water_value"] == pytest.approx(500)  # 10 ha x 10 m3 x 0.5 x R$10
    assert out["roi"] == pytest.approx(-0.7)
    assert out["breakeven_product_cost_per_ha"] == pytest.approx(50)


def test_breakeven_price_gives_zero_roi():
    breakeven = farm_roi(SIMPLE)["breakeven_product_cost_per_ha"]
    assert farm_roi({**SIMPLE, "product_cost_per_ha": breakeven})["roi"] == pytest.approx(0)


def test_missing_input_is_named():
    with pytest.raises(KeyError, match="timing_coverage"):
        farm_roi({k: v for k, v in SIMPLE.items() if k != "timing_coverage"})


def test_range_rejects_bad_order_and_status():
    with pytest.raises(ValueError):
        Range(low=2, base=1, high=3, status="placeholder")
    with pytest.raises(ValueError):
        Range(low=1, base=2, high=3, status="guess")


def test_every_segment_has_every_input():
    assumptions = load(ASSUMPTIONS)
    for key in assumptions.segments:
        ranges = assumptions.inputs_for(key)
        assert set(INPUTS) <= set(ranges), key
        assert "roi_hurdle" in ranges


def test_simulation_is_reproducible_and_stays_in_range():
    ranges = load(ASSUMPTIONS).inputs_for("sugarcane_ground")
    a = simulate(ranges, n=500, seed=1)
    b = simulate(ranges, n=500, seed=1)
    assert len(a) == 500
    assert a.equals(b)
    for name, r in ranges.items():
        assert a[name].between(r.low, r.high).all(), name


def test_summary_reports_hurdle_share():
    ranges = load(ASSUMPTIONS).inputs_for("sugarcane_ground")
    stats = summarise(simulate(ranges, n=500))
    assert stats["roi_p10"] <= stats["roi_median"] <= stats["roi_p90"]
    assert 0 <= stats["share_clearing_hurdle"] <= stats["share_profitable"] <= 1


def test_tornado_puts_biggest_swing_first_and_ignores_fixed_inputs():
    ranges = {name: Range(low=v, base=v, high=v, status="placeholder") for name, v in SIMPLE.items()}
    ranges["value_at_risk_per_ha"] = Range(low=500, base=1000, high=2000, status="placeholder")
    table = tornado(ranges)
    assert table.loc[0, "input"] == "value_at_risk_per_ha"
    assert (table["swing"].iloc[1:] == 0).all()
