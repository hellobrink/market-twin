"""Print the per-farm ROI for every segment in an assumptions file.

Run from the repo root:

    .venv/bin/python -m twin.report
    .venv/bin/python -m twin.report --runs 20000 --assumptions assumptions/nofire_brazil.yaml
"""

import argparse
from pathlib import Path

from twin.assumptions import Assumptions, load
from twin.roi import INPUTS, base_case, simulate, summarise, tornado

DEFAULT_ASSUMPTIONS = Path(__file__).resolve().parent.parent / "assumptions" / "nofire_brazil.yaml"


def money(x: float) -> str:
    return f"R${x:,.0f}"


def pct(x: float) -> str:
    return f"{x:.0%}"


def segment_report(assumptions: Assumptions, key: str, runs: int, seed: int) -> str:
    seg = assumptions.segments[key]
    ranges = assumptions.inputs_for(key)
    base = base_case(ranges)
    stats = summarise(simulate(ranges, n=runs, seed=seed))
    drivers = tornado(ranges).head(5)
    placeholders = sum(ranges[name].status == "placeholder" for name in INPUTS)

    lines = [
        f"{seg.label}  [{key}, {seg.delivery}]",
        "  Base case, per season",
        f"    treated area             {base['treated_ha']:,.1f} ha",
        f"    cost                     {money(base['cost'])}",
        f"    avoided fire loss        {money(base['avoided_loss'])}",
        f"    water saving             {money(base['water_value'])}",
        f"    ROI                      {pct(base['roi'])}",
        f"    break-even product cost  {money(base['breakeven_product_cost_per_ha'])} per ha per application",
        f"  Across {runs:,} runs",
        f"    ROI P10 / median / P90   {pct(stats['roi_p10'])} / {pct(stats['roi_median'])} / {pct(stats['roi_p90'])}",
        f"    profitable               {pct(stats['share_profitable'])} of runs",
        f"    clears buyer's hurdle    {pct(stats['share_clearing_hurdle'])} of runs",
        "  Inputs that move ROI most (each swung low to high, others at base)",
    ]
    for row in drivers.itertuples():
        lines.append(f"    {row.input:<27} {pct(row.at_low):>7} to {pct(row.at_high):<7}  {row.status}")
    lines.append(f"  {placeholders} of {len(INPUTS)} model inputs are still placeholders")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--assumptions", default=DEFAULT_ASSUMPTIONS, type=Path)
    parser.add_argument("--runs", default=10_000, type=int)
    parser.add_argument("--seed", default=0, type=int)
    args = parser.parse_args()

    assumptions = load(args.assumptions)
    print(f"Per-farm ROI, preventive fire treatment ({assumptions.currency})\n")
    print("\n\n".join(segment_report(assumptions, key, args.runs, args.seed) for key in assumptions.segments))


if __name__ == "__main__":
    main()
