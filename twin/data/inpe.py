"""Fetch INPE fire hotspot counts (reference satellite) and match them to IBGE municipality codes."""

import io
import re
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

BASE = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/EstadosBr_sat_ref"

# INPE spellings that differ from IBGE's after normalising accents and punctuation.
ALIASES: dict[str, str] = {}


def normalise_name(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    plain = re.sub(r"[^A-Za-z ]", " ", plain).upper()
    return re.sub(r"\s+", " ", plain).strip()


def download_year(state: str, year: int, cache_dir: Path) -> Path:
    name = f"focos_br_{state.lower()}_ref_{year}.zip"
    path = Path(cache_dir) / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{BASE}/{state.upper()}/{name}", timeout=180) as response:
            path.write_bytes(response.read())
    return path


def read_year(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        frame = pd.read_csv(io.BytesIO(zf.read(csv_name)), usecols=["data_pas", "municipio"])
    frame["year"] = pd.to_datetime(frame["data_pas"]).dt.year
    return frame[["municipio", "year"]]


def match_municipalities(names: pd.Series, municipalities: pd.DataFrame) -> pd.Series:
    """Map INPE municipality names to IBGE codes; unmatched names come back as NaN."""
    lookup = dict(zip(municipalities["name"].map(normalise_name), municipalities["municipality"]))
    keys = names.map(normalise_name).replace(ALIASES)
    return keys.map(lookup)


def hotspot_counts(state: str, years: range, municipalities: pd.DataFrame, cache_dir: Path) -> tuple[pd.DataFrame, list[str]]:
    """Hotspots per municipality per year, plus any INPE names that matched no IBGE municipality.

    Municipalities with no hotspots in a year get an explicit zero.
    """
    frames = [read_year(download_year(state, year, cache_dir)) for year in years]
    spots = pd.concat(frames, ignore_index=True)
    spots["municipality"] = match_municipalities(spots["municipio"], municipalities)
    unmatched = sorted(spots.loc[spots["municipality"].isna(), "municipio"].unique())
    counts = spots.dropna(subset=["municipality"]).groupby(["municipality", "year"]).size()
    grid = pd.MultiIndex.from_product([municipalities["municipality"], list(years)], names=["municipality", "year"])
    counts = counts.reindex(grid, fill_value=0).rename("hotspots").reset_index()
    counts["municipality"] = counts["municipality"].astype(int)
    return counts, unmatched
