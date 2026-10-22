"""Simulate adoption over time across Monte Carlo runs and report the range of outcomes.

Run from the repo root:

    .venv/bin/python -m twin.adoption_report
    .venv/bin/python -m twin.adoption_report --strategy alert --price 300 --runs 500
"""

import argparse
from dataclasses import replace
from pathlib import Path

from twin.adoption import build_market, drivers, simulate_adoption, yearly_summary
from twin.assumptions import Assumptions, Range, load
from twin.data.codes import STATES
from twin.population import StateData, build_population
from twin.report import DEFAULT_ASSUMPTIONS, money, pct


def with_price(assumptions: Assumptions, price: float) -> Assumptions:
    """The same assumptions with the product price fixed, for testing a pricing decision."""
    product = {**assumptions.product, "product_cost_per_ha": Range(price, price, price, "placeholder", "Fixed by --price")}
    return replace(assumptions, product=product)


def millions(x: float) -> str:
    return f"R${x / 1e6:,.1f}m"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default="SP", choices=sorted(STATES))
    parser.add_argument("--assumptions", default=DEFAULT_ASSUMPTIONS, type=Path)
    parser.add_argument("--strategy", default="alert")
    parser.add_argument("--price", type=float, help="fix the product price per hectare per application")
    parser.add_argument("--runs", type=int, help="Monte Carlo runs (default from the assumptions file)")
    parser.add_argument("--seed", default=0, type=int)
    parser.add_argument("--top", default=8, type=int, help="municipalities to list")
    args = parser.parse_args()

    assumptions = load(args.assumptions)
    if args.strategy not in assumptions.strategies:
        parser.error(f"unknown strategy {args.strategy}; choose from {', '.join(assumptions.strategies)}")
    if args.price is not None:
        assumptions = with_price(assumptions, args.price)
    adoption = assumptions.adoption
    runs = args.runs or adoption.runs

    data = StateData.load(args.state)
    market = build_market(build_population(data, seed=args.seed), data, assumptions)
    seasons, draws, by_muni = simulate_adoption(market, assumptions, args.strategy, runs=runs, seed=args.seed)
    no_peers, _, _ = simulate_adoption(market, assumptions, args.strategy, runs=runs, seed=args.seed, peers=False)

    price = assumptions.product["product_cost_per_ha"]
    price_text = money(price.base) if price.low == price.high else f"drawn from {money(price.low)} to {money(price.high)} each run (base {money(price.base)})"
    print(f"Adoption over time: {STATES[args.state]['name']}, {args.strategy} strategy, {runs} runs, "
          f"{adoption.start_year}-{adoption.start_year + adoption.seasons - 1}")
    print(f"Product price per hectare per application: {price_text}")
    print(f"Farms in the market: {market.size:,}. Last severe season before the start: {adoption.last_severe_year}.\n")

    summary = yearly_summary(seasons)
    print(f"  {'year':<6}{'adopters P10 / median / P90':>30}{'revenue P10 / median / P90':>36}{'runs with a severe season by then':>36}")
    for year, row in summary.iterrows():
        adopters = f"{row['adopters_p10']:,.0f} / {row['adopters_median']:,.0f} / {row['adopters_p90']:,.0f}"
        revenue = f"{millions(row['revenue_p10'])} / {millions(row['revenue_median'])} / {millions(row['revenue_p90'])}"
        print(f"  {year:<6}{adopters:>30}{revenue:>36}{pct(row['runs_severe_so_far']):>36}")
    print("  Revenue is product spend by adopters in that season.")

    final = seasons["season"] == seasons["season"].max()
    by_segment = seasons[final].groupby("segment")[["adopters", "willing"]].median()
    print(f"\n  Final year, median across runs")
    print(f"    {'segment':<22}{'adopters':>10}{'would profit':>14}")
    for key, row in by_segment.iterrows():
        print(f"    {key:<22}{row['adopters']:>10,.0f}{row['willing']:>14,.0f}")
    print("    Would profit: farms whose perceived ROI clears their hurdle that season.")

    with_peers = seasons[final].groupby("run")["adopters"].sum().median()
    without = no_peers[no_peers["season"] == no_peers["season"].max()].groupby("run")["adopters"].sum().median()
    print(f"\n  Cooperative and neighbour effects: median final adopters {with_peers:,.0f} with them, {without:,.0f} without")

    print("\n  What moves final adopters most (rank correlation across runs)")
    for name, value in drivers(seasons, draws).head(6).items():
        print(f"    {name:<28}{value:>6.2f}")

    names = data.municipalities.set_index("municipality")["name"]
    order = by_muni.argsort()[::-1][: args.top]
    print("\n  Municipalities with the most adopters in the final year (mean across runs)")
    for i in order:
        print(f"    {names.get(market.municipalities[i], market.municipalities[i]):<30}{by_muni[i]:>8.1f}")


if __name__ == "__main__":
    main()
