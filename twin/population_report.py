"""Build the synthetic farm population for a state and report who would buy, by fire scenario and treatment strategy.

Run from the repo root (after `python -m twin.data.build --state SP`):

    .venv/bin/python -m twin.population_report
    .venv/bin/python -m twin.population_report --scenario severe --strategy alert --top 15
"""

import argparse
from pathlib import Path

import pandas as pd

from twin.assumptions import load
from twin.data.codes import STATES
from twin.population import StateData, add_risk, build_population, evaluate, hotspot_cross_check
from twin.report import DEFAULT_ASSUMPTIONS, money, pct


def population_summary(farms: pd.DataFrame, data: StateData, assumptions) -> str:
    census_total = data.cells.query("activity == 113601 and area_group == 110085")["establishments"].sum()
    in_market = farms.dropna(subset=["segment"])
    lines = [
        f"  {'farms in the census':<34}{census_total:>10,.0f}",
        f"  {'synthetic farms built':<34}{len(farms):>10,}   crop and livestock farms with land",
        f"  {'in the modelled market':<34}{len(in_market):>10,}",
        "",
        f"  {'segment':<22}{'farms':>8}{'median ha':>12}{'median value at risk':>22}",
    ]
    stats = in_market.groupby("segment").agg(
        farms=("area_ha", "size"),
        area=("area_ha", "median"),
        value=("value_at_risk_per_ha", "median"),
    )
    for key, row in stats.iterrows():
        value = money(row["value"]) + "/ha" if pd.notna(row["value"]) else "segment base"
        lines.append(f"  {key:<22}{row['farms']:>8,.0f}{row['area']:>12,.0f}{value:>22}")
    lines.append(f"  Outside the market: {len(farms) - len(in_market):,} farms under 5 ha, large non-cane crop farms or smaller livestock farms.")
    return "\n".join(lines)


def risk_summary(farms: pd.DataFrame) -> str:
    in_market = farms.dropna(subset=["segment"])
    stats = in_market.groupby("segment").agg(
        burn=("burn_rate", "median"),
        chance=("annual_fire_probability", "median"),
        share=("burned_area_if_fire_share", "median"),
    )
    lines = [f"  {'segment':<22}{'burned a year':>15}{'chance of fire':>16}{'share burned if fire':>22}"]
    for key, row in stats.iterrows():
        lines.append(f"  {key:<22}{row['burn']:>14.2%}{pct(row['chance']):>16}{pct(row['share']):>22}")
    lines.append("  Medians. Burned a year is the MapBiomas burn rate for the farm's municipality and land cover.")
    return "\n".join(lines)


def strategy_summary(evaluated: pd.DataFrame, strategy: str, product_price: float, top: int, names: pd.Series) -> str:
    buyers = evaluated[evaluated["clears_hurdle"]]
    lines = [
        f"Strategy: {strategy}  (product at {money(product_price)}/ha per application)",
        f"  {'segment':<22}{'farms':>8}{'median ROI':>12}{'clear hurdle':>14}{'share':>8}{'product spend, buyers':>24}",
    ]
    by_segment = evaluated.groupby("segment").agg(farms=("roi", "size"), roi=("roi", "median"), clear=("clears_hurdle", "sum"))
    spend = buyers.groupby("segment")["product_spend"].sum()
    for key, row in by_segment.iterrows():
        lines.append(
            f"  {key:<22}{row['farms']:>8,.0f}{pct(row['roi']):>12}{row['clear']:>14,.0f}"
            f"{pct(row['clear'] / row['farms']):>8}{money(spend.get(key, 0)):>24}"
        )
    lines.append(
        f"  {'total':<22}{len(evaluated):>8,}{'':>12}{len(buyers):>14,}"
        f"{pct(len(buyers) / len(evaluated)):>8}{money(buyers['product_spend'].sum()):>24}"
    )
    lines.append("  Product spend is per season, at the base price, from farms that clear their ROI hurdle.")
    if top and len(buyers):
        lines.append(f"  Municipalities with the most buyers")
        per_muni = buyers.groupby("municipality").agg(buyers=("roi", "size"), spend=("product_spend", "sum"))
        for code, row in per_muni.sort_values("buyers", ascending=False).head(top).iterrows():
            lines.append(f"    {names.get(code, code):<30}{row['buyers']:>6,.0f} farms{money(row['spend']):>16}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default="SP", choices=sorted(STATES))
    parser.add_argument("--assumptions", default=DEFAULT_ASSUMPTIONS, type=Path)
    parser.add_argument("--scenario", action="append", help="only show this fire scenario; repeat for more")
    parser.add_argument("--strategy", action="append", help="only show this strategy; repeat for more")
    parser.add_argument("--top", default=5, type=int, help="municipalities to list per strategy")
    parser.add_argument("--seed", default=0, type=int)
    args = parser.parse_args()

    assumptions = load(args.assumptions)
    strategies = args.strategy or list(assumptions.strategies)
    scenarios = args.scenario or list(assumptions.fire_scenarios)
    for chosen, known, kind in ((strategies, assumptions.strategies, "strategy"), (scenarios, assumptions.fire_scenarios, "scenario")):
        unknown = set(chosen) - set(known)
        if unknown:
            parser.error(f"unknown {kind} {', '.join(sorted(unknown))}; choose from {', '.join(known)}")

    data = StateData.load(args.state)
    farms = build_population(data, seed=args.seed)
    names = data.municipalities.set_index("municipality")["name"]
    info = data.info
    sources = ""
    if info:
        first, last = info["burned_area"]["years"]
        sources = f"census {info['census']['year']}, crops {info['crops']['year']}, MapBiomas burned area {first}-{last}"

    print(f"Synthetic farm population: {STATES[args.state]['name']} ({sources})")
    print(", ".join(f"{name} {r.base:g} ({r.status})" for name, r in assumptions.population.items()) + "\n")
    print(population_summary(add_risk(farms, data, assumptions, scenarios[0]), data, assumptions))
    product_price = assumptions.product["product_cost_per_ha"].base
    for scenario in scenarios:
        fire = assumptions.fire_scenarios[scenario]
        at_risk = add_risk(farms, data, assumptions, scenario)
        print(f"\n{'=' * 90}\nFire scenario: {scenario} ({fire.first}-{fire.last}). {fire.description}")
        print(f"  Cross-check: INPE hotspots and MapBiomas burned farmland rank municipalities alike at {hotspot_cross_check(data, fire.first, fire.last):.2f}\n")
        print(risk_summary(at_risk))
        for strategy in strategies:
            print()
            print(strategy_summary(evaluate(at_risk, assumptions, strategy), strategy, product_price, args.top, names))


if __name__ == "__main__":
    main()
