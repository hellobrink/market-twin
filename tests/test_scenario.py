from dataclasses import replace

import numpy as np
import pytest

from test_adoption import fixed, fixed_assumptions, tiny_market, with_hurdle
from twin.assumptions import Range, load
from twin.scenario import Plan, Season, World, play, random_world, replay_world


def setup(hurdle=-100.0, **adoption_rates):
    a = with_hurdle(fixed_assumptions(**adoption_rates), hurdle)
    a = replace(a, scenario=replace(a.scenario, rates={k: fixed(r) for k, r in a.scenario.rates.items()}))
    market = tiny_market(a, n=400)
    rates = {"normal": market.rate_normal, "severe": market.rate_severe}
    return a, market, rates.__getitem__


def world_of(*seasons, start=2030):
    return World(start, tuple(seasons), None, "test world")


def test_same_plan_and_seed_replays_exactly_and_a_lower_price_never_loses_users():
    a, market, rates = setup(hurdle=0.0, innovation_rate=0.05)
    world = world_of(*[Season("normal")] * 3, Season("severe"), *[Season("normal")] * 3)
    segments = list(a.segments)
    dear = Plan.constant(7, 1_500, "alert", segments)
    cheap = Plan.constant(7, 300, "alert", segments)
    first = play(market, rates, a, dear, world, farm_seed=4).seasons
    again = play(market, rates, a, dear, world, farm_seed=4).seasons
    assert first.equals(again)
    lower = play(market, rates, a, cheap, world, farm_seed=4).seasons
    assert (lower["adopters"].to_numpy() >= first["adopters"].to_numpy()).all()


def test_a_sales_suspension_stops_sales_and_revenue_for_that_season():
    a, market, rates = setup(innovation_rate=0.3)
    world = world_of(Season("normal"), Season("normal", frozenset({"restriction"})), Season("normal"))
    s = play(market, rates, a, Plan.constant(3, 700, "alert", a.segments), world).seasons
    assert s.loc[1, "new"] == 0 and s.loc[1, "revenue"] == 0
    assert s.loc[0, "revenue"] > 0 and s.loc[2, "revenue"] > 0


def test_a_subsidy_lowers_the_farmer_price_for_its_seasons():
    a, market, rates = setup()
    share, length = a.scenario.events["subsidy"]["share"], a.scenario.events["subsidy"]["seasons"]
    world = world_of(Season("normal", frozenset({"subsidy"})), *[Season("normal")] * length)
    s = play(market, rates, a, Plan.constant(length + 1, 1_000, "alert", a.segments), world).seasons
    assert s["farmer_price"].iloc[:length].tolist() == pytest.approx([1_000 * (1 - share)] * length)
    assert s["farmer_price"].iloc[length] == 1_000
    assert (s["price"] == 1_000).all()  # NoFire still earns the full price


def test_contained_fires_spread_by_word_of_mouth():
    def final_users(weight):
        a, market, rates = setup(innovation_rate=0.01, imitation_rate=0.5)
        a = replace(a, scenario=replace(a.scenario, rates={**a.scenario.rates, "testimonial_weight": Range(weight, weight, weight, "scenario")}))
        world = world_of(*[Season("severe")] * 4)
        return play(market, rates, a, Plan.constant(4, 300, "alert", a.segments), world, farm_seed=1).seasons["adopters"].iloc[-1]

    assert final_users(20) > final_users(0)


def test_only_targeted_segments_adopt():
    a, market, rates = setup(innovation_rate=1.0)
    others = [s for s in a.segments if s != "sugarcane_ground"]
    s = play(market, rates, a, Plan.constant(2, 700, "alert", others), world_of(Season("normal"), Season("normal"))).seasons
    assert (s["adopters"] == 0).all()


def test_random_worlds_are_reproducible_and_a_rival_arrives_once():
    a = load(fixed_assumptions.__globals__["ASSUMPTIONS"])
    a = replace(a, scenario=replace(a.scenario, presets={**a.scenario.presets, "busy": {"severe": 0.5, "subsidy": 0, "restriction": 0,
                                                                                         "competitor": 1.0, "drought": 0, "tax_relief": 1.0}}))
    w1 = random_world(a, "busy", 8, 3, 2027, None)
    assert w1 == random_world(a, "busy", 8, 3, 2027, None)
    assert sum("competitor" in s.shocks for s in w1.seasons) == 1
    assert sum("tax_relief" in s.shocks for s in w1.seasons) == 1


def test_replay_world_uses_the_real_years():
    w = replay_world(2015, 2024)
    assert w.start_year == 2015 and [s.fire for s in w.seasons] == [str(y) for y in range(2015, 2025)]
    assert all(not s.shocks for s in w.seasons)
