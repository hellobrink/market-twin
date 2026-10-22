"""Burned area by land-cover group and municipality, from MapBiomas Fogo collection 5.1 annual rasters.

Each raster covers Brazil at about 30 m. A pixel's value is the MapBiomas land-cover
class that burned that year, or 0 where nothing burned.
"""

import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform

BASE = "https://storage.googleapis.com/mapbiomas-public/initiatives/brazil/fire/collection_05_1/annual_burned_coverage"

# MapBiomas land-cover classes grouped for the twin. Forest plantations (9) count as
# "other" because the synthetic population has no forestry farms.
GROUPS = {
    "cane": {20},
    "pasture": {15},
    "other_farmland": {14, 18, 19, 21, 35, 36, 39, 40, 41, 46, 47, 48, 62},
    "native": {1, 3, 4, 5, 6, 10, 11, 12, 13, 29, 32, 49, 50},
}
GROUP_NAMES = [*GROUPS, "other"]
FARMLAND_GROUPS = ["cane", "pasture", "other_farmland"]


def download_year(year: int, cache_dir: Path) -> Path:
    path = Path(cache_dir) / f"coverage_{year}.tif"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{BASE}/annual_burned_coverage-brazil_burned_coverage_{year}.tif"
        with urllib.request.urlopen(url, timeout=600) as response:
            path.write_bytes(response.read())
    return path


def _group_lookup() -> np.ndarray:
    lookup = np.full(256, GROUP_NAMES.index("other"), dtype=np.int64)
    for i, name in enumerate(GROUPS):
        lookup[list(GROUPS[name])] = i
    return lookup


def pixel_hectares(transform, rows: int) -> np.ndarray:
    """Area of one pixel in each row, in hectares, for a lat/lon grid."""
    lat = transform.f + transform.e * (np.arange(rows) + 0.5)
    width_m = transform.a * 111_320 * np.cos(np.radians(lat))
    height_m = abs(transform.e) * 110_574
    return width_m * height_m / 10_000


def burned_area_by_municipality(rasters: dict[int, Path], boundaries: gpd.GeoDataFrame, block_rows: int = 1024) -> pd.DataFrame:
    """Hectares burned per municipality, year and land-cover group.

    `boundaries` needs a `municipality` code column and polygons in EPSG:4326. The
    rasters are read in strips across the state so memory stays small.
    """
    years = sorted(rasters)
    datasets = [rasterio.open(rasters[y]) for y in years]
    try:
        ref = datasets[0]
        if any(ds.transform != ref.transform for ds in datasets):
            raise ValueError("MapBiomas rasters for different years are on different grids")
        state = from_bounds(*boundaries.total_bounds, ref.transform).round_offsets().round_lengths()
        shapes = [(geom, i + 1) for i, geom in enumerate(boundaries.geometry)]
        n_places, n_groups = len(boundaries) + 1, len(GROUP_NAMES)
        totals = np.zeros((len(years), n_places, n_groups))
        lookup = _group_lookup()

        for row in range(0, int(state.height), block_rows):
            strip = Window(state.col_off, state.row_off + row, state.width, min(block_rows, state.height - row))
            transform = window_transform(strip, ref.transform)
            ids = rasterize(shapes, out_shape=(int(strip.height), int(strip.width)), transform=transform, fill=0, dtype="uint16")
            area = np.broadcast_to(pixel_hectares(transform, ids.shape[0])[:, None], ids.shape)
            for i, ds in enumerate(datasets):
                classes = ds.read(1, window=strip)
                burned = (classes > 0) & (ids > 0)
                key = ids[burned].astype(np.int64) * n_groups + lookup[classes[burned]]
                totals[i] += np.bincount(key, weights=area[burned], minlength=n_places * n_groups).reshape(n_places, n_groups)
    finally:
        for ds in datasets:
            ds.close()

    codes = boundaries["municipality"].to_numpy()
    frames = [
        pd.DataFrame(totals[i, 1:], columns=[f"{g}_ha" for g in GROUP_NAMES]).assign(municipality=codes, year=year)
        for i, year in enumerate(years)
    ]
    out = pd.concat(frames, ignore_index=True)
    return out[["municipality", "year", *[f"{g}_ha" for g in GROUP_NAMES]]]
