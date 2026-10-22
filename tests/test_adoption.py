from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from twin.adoption import Market, drivers, run_once, simulate_adoption, yearly_summary
from twin.assumptions import Range, load
from twin.roi import farm_roi

ASSUMPTIONS = Path(__file__).resolve().parent.parent / "assumptions" / "nofire_brazil.yaml"


def fixed(r: Range) -> Range:
    return Range(r.base, r.base, r.base, r.status)


def fixed_assumptions(**adoption_rates):
    """Every range collapsed to its base value, with chosen adoption rates, so runs are predictable."""
    a = load(ASSUMPTIONS)
    segments = {
        k: replace(s, params={n: fixed(r) for n, r in s.params.items()},
                   strategies={st: {n: fixed(r) for n, r in p.items()} for st, p in s.strategies.items()})
        for k, s in a.segments.items()
    }
    rates = {n: fixed(r) for n, r in a.adoption.rates.items()}
    rates.update({n: Range(v, v, v, "placeholder") for n, v in adoption_rates.items()})
    adoption = replace(a.adoption, rates=rates, coop_member_share={k: fixed(r) for k, r in a.adoption.coop_member_share.items()})
    return replace(
        a,
        segments=segments,
        product={n: fixed(r) for n, r in a.product.items()},
        delivery={m: {n: fixed(r) for n, r in d.items()} for m, d in a.delivery.items()},
        population={n: fixed(r) for n, r in a.population.items()},
        adoption=adoption,
    )


def tiny_market(assumptions, n: int = 40) -> Market:
    """n sugarcane farms of 300 ha in two municipalities, with low normal and high severe burn rates."""
    cane = list(assumptions.segments).index("sugarcane_ground")
    return Market(
        segments=list(assumptions.segments),
        segment_index=np.full(n, cane),
        municipalities=np.array([1, 2]),
        municipality_index=np.arange(n) % 2,
        area_ha=np.full(n, 300.0),
        rate_normal=np.full(n, 0.001),
        rate_severe=np.full(n, 0.2),
        cane_value_per_ha=np.full(n, 10_000.0),
    )


def roi_at(assumptions, market: Market, rate: float) -> float:
    inputs = {name: r.base for name, r in assumptions.inputs_for("sugarcane_ground", "alert").items()}
    inputs.update(farm_area_ha=300.0, annual_fire_probability=1.0, burned_area_if_fire_share=rate,
                  value_at_risk_per_ha=10_000 * assumptions.population["sugarcane_fire_loss_share"].base)
    return float(farm_roi(inputs)["roi"])


def with_hurdle(assumptions, hurdle: float):
    return replace(assumptions, buyer={"roi_hurdle": Range(hurdle, hurdle, hurdle, "placeholder")})


def test_everyone_willing_adopts_at_once_when_innovation_is_certain():
    a = with_hurdle(fixed_assumptions(innovation_rate=1.0), -100)
    rows, _ = run_once(tiny_market(a), a, "alert", np.random.default_rng(0))
    first = rows[(rows["season"] == 1) & (rows["segment"] == "sugarcane_ground")].iloc[0]
    assert first["adopters"] == first["willing"] == 40


def test_nobody_adopts_without_an_outside_push():
    a = with_hurdle(fixed_assumptions(innovation_rate=0.0), -100)
    rows, _ = run_once(tiny_market(a), a, "alert", np.random.default_rng(0))
    assert rows["adopters"].sum() == 0


def test_a_severe_season_makes_farms_willing_and_the_memory_fades():
    a = fixed_assumptions(innovation_rate=0.0, severe_year_probability=1.0, risk_memory_half_life=1.0)
    a = replace(a, adoption=replace(a.adoption, start_year=2040, last_severe_year=2000, seasons=3))
    market = tiny_market(a)
    hurdle = (roi_at(a, market, 0.001) + roi_at(a, market, 0.2)) / 2
    rows, _ = run_once(market, with_hurdle(a, hurdle), "alert", np.random.default_rng(0))
    willing = rows[rows["segment"] == "sugarcane_ground"].set_index("season")["willing"]
    assert willing[1] == 0  # 40 seasons since the last severe year: risk feels normal
    assert willing[2] == 40  # the first season was severe


def test_peer_effects_add_adopters():
    a = with_hurdle(fixed_assumptions(innovation_rate=0.05, imitation_rate=0.6), -100)
    market = tiny_market(a, n=2_000)
    with_peers, _, _ = simulate_adoption(market, a, "alert", runs=5, seed=1)
    without, _, _ = simulate_adoption(market, a, "alert", runs=5, seed=1, peers=False)
    last = with_peers["season"].max()
    assert with_peers.query("season == @last")["adopters"].sum() > without.query("season == @last")["adopters"].sum()


def test_summary_and_drivers_have_one_row_per_year_and_input():
    a = load(ASSUMPTIONS)
    market = tiny_market(a)
    seasons, draws, by_muni = simulate_adoption(market, a, "alert", runs=20, seed=2)
    summary = yearly_summary(seasons)
    assert list(summary.index) == list(range(a.adoption.start_year, a.adoption.start_year + a.adoption.seasons))
    assert (summary["adopters_p10"] <= summary["adopters_median"]).all()
    assert (summary["adopters_median"] <= summary["adopters_p90"]).all()
    assert set(drivers(seasons, draws).index) == set(draws.columns)
    assert len(by_muni) == 2 and by_muni.sum() == pytest.approx(seasons.query("season == @a.adoption.seasons")["adopters"].sum() / 20)
