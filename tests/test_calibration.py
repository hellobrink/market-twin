from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from twin.assumptions import load
from twin.calibration import burned_share, expected_burned_ha, solve_k
from twin.data.mapbiomas import burned_area_by_municipality, pixel_hectares

ASSUMPTIONS = Path(__file__).resolve().parent.parent / "assumptions" / "nofire_brazil.yaml"


def test_solve_k_recovers_the_value_that_made_the_target():
    rng = np.random.default_rng(0)
    area = rng.uniform(10, 2_000, 500)
    rate = rng.uniform(0, 1e-3, 500)
    share = np.full(500, 0.2)
    target = expected_burned_ha(0.8, area, rate, share)
    assert solve_k(area, rate, share, target) == pytest.approx(0.8, rel=1e-6)


def test_solve_k_rejects_targets_the_population_cannot_reach():
    area, rate, share = np.array([100.0]), np.array([1e-3]), np.array([0.2])
    with pytest.raises(ValueError):
        solve_k(area, rate, share, target=25)  # at most 20 ha can burn


def test_burned_share_borrows_from_the_nearest_segment():
    assumptions = load(ASSUMPTIONS)
    base = {k: s.params["burned_area_if_fire_share"].base for k, s in assumptions.segments.items()}
    farms = pd.DataFrame({
        "activity": ["temporary_crops", "temporary_crops", "livestock", "horticulture"],
        "area_ha": [300, 300, 50, 10],
        "segment": ["sugarcane_ground", None, None, "smallholder_ground"],
    })
    assert burned_share(farms, assumptions).tolist() == [
        base["sugarcane_ground"], base["sugarcane_ground"], base["remote_ranch_drone"], base["smallholder_ground"],
    ]


def test_burned_area_is_summed_by_municipality_and_land_cover(tmp_path):
    # A 4 x 4 grid of 0.01 degree pixels at the equator; two municipalities split it down the middle.
    transform = from_origin(0, 0.04, 0.01, 0.01)
    classes = np.array([
        [20, 20, 15, 0],
        [20, 0, 3, 0],
        [0, 0, 0, 0],
        [41, 0, 0, 9],
    ], dtype="uint8")
    path = tmp_path / "coverage_2020.tif"
    with rasterio.open(path, "w", driver="GTiff", width=4, height=4, count=1, dtype="uint8", crs="EPSG:4326", transform=transform) as dst:
        dst.write(classes, 1)
    boundaries = gpd.GeoDataFrame({"municipality": [1, 2]}, geometry=[box(0, 0, 0.02, 0.04), box(0.02, 0, 0.04, 0.04)], crs="EPSG:4326")

    result = burned_area_by_municipality({2020: path}, boundaries, block_rows=3).set_index("municipality")
    pixel = pixel_hectares(transform, 1)[0]
    assert pixel == pytest.approx(111_320 * 0.01 * 110_574 * 0.01 / 10_000, rel=1e-3)
    assert result.loc[1, "cane_ha"] == pytest.approx(3 * pixel, rel=1e-3)
    assert result.loc[1, "other_farmland_ha"] == pytest.approx(pixel, rel=1e-3)
    assert result.loc[2, "pasture_ha"] == pytest.approx(pixel, rel=1e-3)
    assert result.loc[2, "native_ha"] == pytest.approx(pixel, rel=1e-3)
    assert result.loc[2, "other_ha"] == pytest.approx(pixel, rel=1e-3)  # forest plantation
    assert (result["year"] == 2020).all()
