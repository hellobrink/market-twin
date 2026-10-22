"""Fetch tables from IBGE's SIDRA API and municipality lists, with a local cache."""

import gzip
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

SIDRA = "https://servicodados.ibge.gov.br/api/v3/agregados"
LOCALIDADES = "https://servicodados.ibge.gov.br/api/v1/localidades"


def get_json(url: str, cache_dir: Path | None = None):
    """GET a JSON URL, reading from and writing to cache_dir when given."""
    cache = None
    if cache_dir is not None:
        cache = Path(cache_dir) / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.json"
        if cache.exists():
            return json.loads(cache.read_text())
    with urllib.request.urlopen(url, timeout=180) as response:
        body = response.read()
    if body[:2] == b"\x1f\x8b":  # IBGE sometimes gzips responses without being asked
        body = gzip.decompress(body)
    data = json.loads(body)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False))
    return data


def parse_value(raw: str) -> float:
    """SIDRA cells are strings. "-" means zero; "X" (suppressed), ".." and "..." mean unknown."""
    if raw == "-":
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def sidra_url(table: int, period: str, variables: list[int], classifications: dict[int, list[int]], localidades: str) -> str:
    cls = "|".join(f"{c}[{','.join(map(str, cats))}]" for c, cats in classifications.items())
    query = urllib.parse.urlencode({"localidades": localidades, "classificacao": cls}, safe="[]|,")
    return f"{SIDRA}/{table}/periodos/{period}/variaveis/{'|'.join(map(str, variables))}?{query}"


def parse_sidra(data: list) -> pd.DataFrame:
    """Flatten a SIDRA v3 response into one row per variable, category combination, place and period."""
    rows = []
    for var in data:
        for result in var["resultados"]:
            cats = {f"c{c['id']}": int(next(iter(c["categoria"]))) for c in result["classificacoes"]}
            for series in result["series"]:
                for period, raw in series["serie"].items():
                    rows.append({
                        "variable": int(var["id"]),
                        **cats,
                        "municipality": int(series["localidade"]["id"]),
                        "period": int(period),
                        "raw": raw,
                        "value": parse_value(raw),
                    })
    return pd.DataFrame(rows)


def sidra(table: int, period: str, variables: list[int], classifications: dict[int, list[int]],
          state_code: int, cache_dir: Path | None = None) -> pd.DataFrame:
    """One SIDRA table for every municipality in a state."""
    url = sidra_url(table, period, variables, classifications, localidades=f"N6[N3[{state_code}]]")
    return parse_sidra(get_json(url, cache_dir))


def municipal_boundaries(state_code: int, cache_dir: Path | None = None):
    """Municipality polygons for a state (EPSG:4326) with a `municipality` code column."""
    import geopandas as gpd  # only needed for the burned-area step

    url = (f"https://servicodados.ibge.gov.br/api/v3/malhas/estados/{state_code}"
           "?formato=application/vnd.geo%2Bjson&intrarregiao=municipio&qualidade=intermediaria")
    frame = gpd.GeoDataFrame.from_features(get_json(url, cache_dir)["features"], crs="EPSG:4326")
    frame["municipality"] = frame["codarea"].astype(int)
    return frame[["municipality", "geometry"]]


def municipalities(state_code: int, cache_dir: Path | None = None) -> pd.DataFrame:
    data = get_json(f"{LOCALIDADES}/estados/{state_code}/municipios", cache_dir)
    return pd.DataFrame({"municipality": [m["id"] for m in data], "name": [m["nome"] for m in data]})
