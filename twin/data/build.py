"""Download IBGE and INPE data for one state and write the processed tables the population builder reads.

Run from the repo root:

    .venv/bin/python -m twin.data.build --state SP

Raw downloads are cached in data/raw/<state>/ (not committed). Processed tables go to
data/processed/<state>/ and are committed, so the rest of the twin runs offline.
"""

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from twin.data import ibge, inpe
from twin.data.codes import ACTIVITIES, ACTIVITY_TOTAL, AREA_GROUP_TOTAL, AREA_GROUPS, CROP_ALL, CROP_SUGARCANE, STATES

ROOT = Path(__file__).resolve().parents[2] / "data"

CENSUS_YEAR = "2017"
TYPOLOGY_TOTAL = {829: [46302]}
LAND_TENURE_TOTAL = {221: [111195]}
AREA_GROUP_CODES = [AREA_GROUP_TOTAL, *AREA_GROUPS]


def census_cells(state_code: int, cache: Path) -> pd.DataFrame:
    """Establishments and area by municipality, activity group and area group (table 6754).

    Fetched one activity at a time to stay under SIDRA's per-request limit.
    """
    frames = []
    for activity in [ACTIVITY_TOTAL, *ACTIVITIES]:
        frames.append(ibge.sidra(
            6754, CENSUS_YEAR, [183, 184],
            {**TYPOLOGY_TOTAL, **LAND_TENURE_TOTAL, 12517: [activity], 220: AREA_GROUP_CODES},
            state_code, cache,
        ))
    raw = pd.concat(frames, ignore_index=True)
    wide = raw.pivot_table(index=["municipality", "c12517", "c220"], columns="variable", values="value", dropna=False)
    wide = wide.rename(columns={183: "establishments", 184: "area_ha"}).reset_index()
    return wide.rename(columns={"c12517": "activity", "c220": "area_group"})


def trucks(state_code: int, cache: Path) -> pd.DataFrame:
    """Establishments with at least one truck, by municipality and area group (table 6877)."""
    raw = ibge.sidra(
        6877, CENSUS_YEAR, [10002],
        {**TYPOLOGY_TOTAL, 797: [40621], 12603: [45927], 220: AREA_GROUP_CODES},
        state_code, cache,
    )
    return raw.rename(columns={"c220": "area_group", "value": "establishments_with_trucks"})[
        ["municipality", "area_group", "establishments_with_trucks"]
    ]


def crops(state_code: int, year: str, cache: Path) -> pd.DataFrame:
    """Planted area, harvested area and production value for sugarcane and all crops (PAM, table 5457)."""
    raw = ibge.sidra(5457, year, [8331, 216, 215], {782: [CROP_ALL, CROP_SUGARCANE]}, state_code, cache)
    names = {
        (CROP_ALL, 8331): "all_crops_planted_ha",
        (CROP_SUGARCANE, 8331): "cane_planted_ha",
        (CROP_SUGARCANE, 216): "cane_harvested_ha",
        (CROP_SUGARCANE, 215): "cane_value_brl",
    }
    raw["column"] = [names.get((c, v)) for c, v in zip(raw["c782"], raw["variable"])]
    wide = raw.dropna(subset=["column"]).pivot_table(index="municipality", columns="column", values="value", dropna=False)
    wide["cane_value_brl"] *= 1_000  # SIDRA reports production value in thousands of reais
    return wide.reset_index()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default="SP", choices=sorted(STATES))
    parser.add_argument("--crop-year", default="2024")
    parser.add_argument("--hotspot-years", default="2015-2024", help="inclusive range for hotspots and burned area, e.g. 2015-2024")
    parser.add_argument("--land-cover-year", default=2020, type=int, help="MapBiomas land-cover year used to turn burned area into burn rates")
    args = parser.parse_args()

    state = STATES[args.state]
    first, last = map(int, args.hotspot_years.split("-"))
    years = range(first, last + 1)
    cache = ROOT / "raw" / args.state.lower()
    out = ROOT / "processed" / args.state.lower()
    out.mkdir(parents=True, exist_ok=True)

    munis = ibge.municipalities(state["ibge_code"], cache)
    munis.to_csv(out / "municipalities.csv", index=False)
    print(f"{len(munis)} municipalities")

    cells = census_cells(state["ibge_code"], cache)
    cells.to_csv(out / "census_cells.csv", index=False)
    print(f"census cells: {len(cells):,} rows")

    trucks(state["ibge_code"], cache).to_csv(out / "trucks.csv", index=False)
    crops(state["ibge_code"], args.crop_year, cache).to_csv(out / "crops.csv", index=False)

    spots, unmatched = inpe.hotspot_counts(args.state, years, munis, cache)
    spots.to_csv(out / "hotspots.csv", index=False)
    print(f"hotspots: {int(spots['hotspots'].sum()):,} across {len(years)} years")
    if unmatched:
        print(f"INPE names with no IBGE match ({len(unmatched)}): {', '.join(unmatched)}")

    from twin.data import mapbiomas  # needs geopandas and rasterio

    boundaries = ibge.municipal_boundaries(state["ibge_code"], cache)
    rasters = {year: mapbiomas.download_year(year, cache / "mapbiomas") for year in years}
    burned = mapbiomas.area_by_municipality(rasters, boundaries)
    burned.round(2).to_csv(out / "burned_area.csv", index=False)
    farmland = burned[[f"{g}_ha" for g in mapbiomas.FARMLAND_GROUPS]].sum(axis=1)
    print(f"burned farmland: {farmland.sum() / len(years):,.0f} ha a year on average")

    cover = mapbiomas.area_by_municipality({args.land_cover_year: mapbiomas.land_cover_url(args.land_cover_year)}, boundaries, block_rows=2048)
    cover.round(2).to_csv(out / "land_cover.csv", index=False)
    print(f"land cover {args.land_cover_year}: {cover.filter(like='_ha').sum().sum() / 1e6:.1f} Mha mapped")

    (out / "build_info.json").write_text(json.dumps({
        "state": args.state,
        "built": date.today().isoformat(),
        "census": {"source": "IBGE Censo Agropecuário", "year": CENSUS_YEAR, "tables": [6754, 6877]},
        "crops": {"source": "IBGE Produção Agrícola Municipal", "year": args.crop_year, "table": 5457},
        "hotspots": {"source": "INPE BDQueimadas, reference satellite", "years": [first, last]},
        "burned_area": {"source": "MapBiomas Fogo collection 5.1, annual burned coverage", "years": [first, last]},
        "land_cover": {"source": "MapBiomas collection 11 land cover", "year": args.land_cover_year},
        "unmatched_hotspot_names": unmatched,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
