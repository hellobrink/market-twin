"""Build the synthetic farm population for a state and report who would buy under each treatment strategy.

Run from the repo root (after `python -m twin.data.build --state SP`):

    .venv/bin/python -m twin.population_report
    .venv/bin/python -m twin.population_report --strategy alert --top 15
"""

import argparse
from pathlib import Path

import pandas as pd

from twin.assumptions import load
from twin.data.codes import STATES
from twin.population import StateData, add_risk, build_population, evaluate
from twin.report import DEFAULT_ASSUMPTIONS, money, pct


def population_summary(farms: pd.DataFrame, data: StateData, assumptions) -> str:
    census_total = data.cells.query("activity == 113601 and area_group == 110085")["establishments"].sum()
    in_market = farms.dropna(subset=["segment"])
    lines = [
        f"  {'farms in the census':<34}{census_total:>10,.0f}",
        f"  {'synthetic farms built':<34}{len(farms):>10,}   crop and livestock farms with land",
        f"  {'in the modelled market':<34}{len(in_market):>10,}",
        "",
        f"  {'segment':<22}{'farms':>8}{'median ha':>12}{'median fire prob':>18}{'median value at risk':>22}",
    ]
    stats = in_market.groupby("segment").agg(
        farms=("area_ha", "size"),
        area=("area_ha", "median"),
        fire=("annual_fire_probability", "median"),
        value=("value_at_risk_per_ha", "median"),
    )
    for key, row in stats.iterrows():
        value = money(row["value"]) + "/ha" if pd.notna(row["value"]) else "segment base"
        lines.append(f"  {key:<22}{row['farms']:>8,.0f}{row['area']:>12,.0f}{pct(row['fire']):>18}{value:>22}")
    lines.append(f"  Outside the market: {len(farms) - len(in_market):,} farms under 5 ha, large non-cane crop farms or smaller livestock farms.")
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
    parser.add_argument("--strategy", action="append", help="only show this strategy; repeat for more")
    parser.add_argument("--top", default=10, type=int, help="municipalities to list per strategy")
    parser.add_argument("--seed", default=0, type=int)
    args = parser.parse_args()

    assumptions = load(args.assumptions)
    strategies = args.strategy or list(assumptions.strategies)
    unknown = set(strategies) - set(assumptions.strategies)
    if unknown:
        parser.error(f"unknown strategy {', '.join(sorted(unknown))}; choose from {', '.join(assumptions.strategies)}")

    data = StateData.load(args.state)
    pop = assumptions.population
    farms = add_risk(
        build_population(data, seed=args.seed), data,
        fires_per_hotspot=pop["fires_per_hotspot"].base,
        sugarcane_fire_loss_share=pop["sugarcane_fire_loss_share"].base,
    )
    names = data.municipalities.set_index("municipality")["name"]
    info = data.info
    sources = ""
    if info:
        first, last = info["hotspots"]["years"]
        sources = f"census {info['census']['year']}, crops {info['crops']['year']}, hotspots {first}-{last}"

    print(f"Synthetic farm population: {STATES[args.state]['name']} ({sources})")
    print(", ".join(f"{name} {r.base:g} ({r.status})" for name, r in pop.items()) + "\n")
    print(population_summary(farms, data, assumptions))
    for strategy in strategies:
        product_price = assumptions.product["product_cost_per_ha"].base
        print()
        print(strategy_summary(evaluate(farms, assumptions, strategy), strategy, product_price, args.top, names))


if __name__ == "__main__":
    main()
