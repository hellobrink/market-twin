from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from twin.assumptions import load
from twin.data.codes import ACTIVITY_TOTAL, AREA_GROUP_TOTAL
from twin.data.ibge import parse_sidra, parse_value
from twin.data.inpe import match_municipalities, normalise_name
from twin.population import (
    StateData, add_risk, assign_segments, build_population, burn_rates, evaluate, impute_suppressed_areas, sample_areas,
    truck_share,
)

ASSUMPTIONS = Path(__file__).resolve().parent.parent / "assumptions" / "nofire_brazil.yaml"

TEMP, HORTI, LIVESTOCK = 111519, 111520, 111523
G10_20, G100_200, G500_1000 = 111552, 111555, 111557


def tiny_state() -> StateData:
    """Two municipalities: 1 grows sugarcane and has fires, 2 has neither."""
    cells = pd.DataFrame([
        # municipality, activity, area_group, establishments, area_ha
        (1, ACTIVITY_TOTAL, AREA_GROUP_TOTAL, 35, 10_000),
        (1, ACTIVITY_TOTAL, G10_20, 20, 300),
        (1, ACTIVITY_TOTAL, G100_200, 10, 1_500),
        (1, ACTIVITY_TOTAL, G500_1000, 5, 4_000),
        (1, TEMP, G100_200, 10, 1_500),
        (1, HORTI, G10_20, 20, 300),
        (1, LIVESTOCK, G500_1000, 5, np.nan),  # area suppressed by IBGE
        (2, ACTIVITY_TOTAL, AREA_GROUP_TOTAL, 4, 600),
        (2, ACTIVITY_TOTAL, G100_200, 4, 600),
        (2, TEMP, G100_200, 4, 600),
    ], columns=["municipality", "activity", "area_group", "establishments", "area_ha"])
    trucks = pd.DataFrame([
        (1, G10_20, 20),  # every small farm in municipality 1 has a truck
        (1, G100_200, 5),
        (1, G500_1000, np.nan),  # suppressed: falls back to the state share for that size
        (2, G100_200, 0),
    ], columns=["municipality", "area_group", "establishments_with_trucks"])
    crops = pd.DataFrame([
        (1, 1_000, 1_000, 1_000, 10_000_000),  # all sugarcane, R$10,000/ha
        (2, 500, 0, 0, 0),
    ], columns=["municipality", "all_crops_planted_ha", "cane_planted_ha", "cane_harvested_ha", "cane_value_brl"])
    hotspots = pd.DataFrame([(1, 2023, 10), (1, 2024, 30), (2, 2023, 0), (2, 2024, 0)],
                            columns=["municipality", "year", "hotspots"])
    munis = pd.DataFrame({"municipality": [1, 2], "name": ["Alpha", "Beta"]})
    cover = ["cane_ha", "pasture_ha", "other_farmland_ha", "native_ha", "other_ha"]
    burned = pd.DataFrame([
        (1, 2023, 1_000, 100, 50, 0, 0),
        (1, 2024, 9_000, 300, 5_000, 0, 0),
        (2, 2023, 0, 0, 0, 0, 0),
        (2, 2024, 0, 0, 0, 0, 0),
    ], columns=["municipality", "year", *cover])
    land_cover = pd.DataFrame([(1, 2020, 100_000, 20_000, 10_000, 0, 0), (2, 2020, 0, 0, 600, 0, 0)],
                              columns=["municipality", "year", *cover])
    return StateData(municipalities=munis, cells=cells, trucks=trucks, crops=crops, hotspots=hotspots, info={},
                     burned=burned, land_cover=land_cover)


def test_sample_areas_stay_in_group_and_match_census_mean():
    rng = np.random.default_rng(0)
    for mean in (110, 130, 150, 190):
        areas = sample_areas(rng, 50_000, 100, 200, total_area=50_000 * mean)
        assert areas.min() >= 100 and areas.max() < 200
        assert areas.mean() == pytest.approx(mean, rel=0.01)


def test_sample_areas_fall_back_when_census_area_is_missing_or_open_ended():
    rng = np.random.default_rng(0)
    assert sample_areas(rng, 50_000, 100, 200, np.nan).mean() == pytest.approx(150, rel=0.01)
    assert (sample_areas(rng, 3, 10_000, None, 45_000) == 15_000).all()


def test_suppressed_area_is_filled_from_the_published_total():
    cells = pd.DataFrame([
        (1, LIVESTOCK, AREA_GROUP_TOTAL, 12, 1_650),
        (1, LIVESTOCK, G10_20, 10, 150),  # published
        (1, LIVESTOCK, G500_1000, 2, np.nan),  # suppressed: gets the 1,500 ha left over
        (2, LIVESTOCK, AREA_GROUP_TOTAL, 3, np.nan),  # total suppressed too
        (2, LIVESTOCK, G500_1000, 3, np.nan),
    ], columns=["municipality", "activity", "area_group", "establishments", "area_ha"])
    filled = impute_suppressed_areas(cells).set_index(["municipality", "area_group"])
    assert filled.loc[(1, G500_1000), "area_ha"] == pytest.approx(1_500)
    assert filled.loc[(1, G10_20), "area_ha"] == 150
    assert np.isnan(filled.loc[(2, G500_1000), "area_ha"])

    capped = cells.assign(area_ha=cells["area_ha"].replace(1_650, 9_000))
    filled = impute_suppressed_areas(capped).set_index(["municipality", "area_group"])
    assert filled.loc[(1, G500_1000), "area_ha"] == pytest.approx(2_000)  # 2 farms can hold at most 2 x 1,000 ha


def test_truck_share_uses_state_share_where_suppressed():
    shares = truck_share(tiny_state()).set_index(["municipality", "area_group"])["truck_share"]
    assert shares[(1, G10_20)] == 1.0
    assert shares[(1, G100_200)] == 0.5
    assert shares[(1, G500_1000)] == 0.0  # no truck data for that size anywhere, so the state share is 0


def test_population_has_one_farm_per_establishment_and_is_reproducible():
    data = tiny_state()
    a = build_population(data, seed=3)
    b = build_population(data, seed=3)
    assert len(a) == 10 + 20 + 5 + 4
    assert a.equals(b)


def test_segment_rules():
    farms = pd.DataFrame({
        "activity": ["temporary_crops", "temporary_crops", "horticulture", "horticulture", "livestock", "livestock", "temporary_crops"],
        "area_ha": [300, 300, 20, 20, 800, 100, 2],
        "has_truck": [True, True, True, False, True, True, True],
        "cane_share": [1.0, 0.0, 0, 0, 0, 0, 1.0],
    })
    segments = [s if isinstance(s, str) else None for s in assign_segments(farms, cane_draw=np.full(len(farms), 0.5))]
    assert segments == ["sugarcane_ground", None, "smallholder_ground", "smallholder_drone", "remote_ranch_drone", None, None]


def test_burn_rates_divide_burned_by_land_and_lean_on_the_state_rate_where_land_is_scarce():
    data = tiny_state()
    raw = burn_rates(data, 2024, 2024, prior_ha=0)
    assert raw.loc[1, "cane"] == pytest.approx(0.09) and raw.loc[1, "pasture"] == pytest.approx(0.015)
    pulled = burn_rates(data, 2024, 2024)
    assert pulled.loc[2, "cane"] == pytest.approx(0.09)  # no cane land: the state rate


def test_risk_comes_from_burn_rates_and_cane_value():
    data = tiny_state()
    assumptions = load(ASSUMPTIONS)
    assert assumptions.fire_scenarios["severe"].first == 2024
    farms = add_risk(build_population(data), data, assumptions, "severe")
    cane = farms[(farms["municipality"] == 1) & (farms["segment"] == "sugarcane_ground")]
    assert len(cane) == 10
    assert np.allclose(cane["burn_rate"], burn_rates(data, 2024, 2024).loc[1, "cane"])
    assert np.allclose(cane["annual_fire_probability"] * cane["burned_area_if_fire_share"], cane["burn_rate"])
    assert (cane["value_at_risk_per_ha"] == 6_000).all()  # R$10,000/ha x 0.6 loss share
    small = farms[(farms["municipality"] == 1) & farms["segment"].isin(["smallholder_ground", "smallholder_drone"])]
    assert (small["annual_fire_probability"] == 1).all()  # burn rate above the 25% share: chance capped
    assert np.allclose(small["burned_area_if_fire_share"], small["burn_rate"])
    assert farms.loc[farms["segment"] != "sugarcane_ground", "value_at_risk_per_ha"].isna().all()


def test_evaluate_uses_data_where_given_and_segment_base_otherwise():
    data = tiny_state()
    assumptions = load(ASSUMPTIONS)
    farms = add_risk(build_population(data), data, assumptions, "normal")
    result = evaluate(farms, assumptions, "alert")
    assert result["segment"].notna().all()
    cane = result[result["segment"] == "sugarcane_ground"]
    assert (cane["value_at_risk_per_ha"] == 6_000).all()
    ground = result[result["segment"] == "smallholder_ground"]
    assert (ground["value_at_risk_per_ha"] == assumptions.inputs_for("smallholder_ground", "alert")["value_at_risk_per_ha"].base).all()
    hurdle = assumptions.buyer["roi_hurdle"].base
    assert (result["clears_hurdle"] == (result["roi"] > hurdle)).all()


def test_parse_sidra_reads_markers_and_categories():
    assert parse_value("-") == 0 and np.isnan(parse_value("X")) and parse_value("12.5") == 12.5
    data = [{"id": "183", "resultados": [{
        "classificacoes": [{"id": "220", "categoria": {"111554": "De 50 a menos de 100 ha"}}],
        "series": [{"localidade": {"id": "3550308"}, "serie": {"2017": "X"}}],
    }]}]
    row = parse_sidra(data).iloc[0]
    assert (row["variable"], row["c220"], row["municipality"], row["period"], row["raw"]) == (183, 111554, 3550308, 2017, "X")


def test_inpe_names_match_ibge_names():
    assert normalise_name("SANTA BÁRBARA D'OESTE") == "SANTA BARBARA D OESTE"
    munis = pd.DataFrame({"municipality": [10, 20], "name": ["Santa Bárbara d'Oeste", "São Paulo"]})
    codes = match_municipalities(pd.Series(["SANTA BÁRBARA D'OESTE", "SÃO PAULO", "NOWHERE"]), munis)
    assert codes.tolist()[:2] == [10, 20] and np.isnan(codes.iloc[2])
