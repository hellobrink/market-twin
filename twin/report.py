"""Print the per-farm ROI for every segment and treatment strategy in an assumptions file.

Run from the repo root:

    .venv/bin/python -m twin.report
    .venv/bin/python -m twin.report --strategy alert
    .venv/bin/python -m twin.report --runs 20000 --assumptions assumptions/nofire_brazil.yaml
"""

import argparse
from pathlib import Path

from twin.assumptions import Assumptions, load
from twin.roi import INPUTS, base_case, simulate, summarise, tornado

DEFAULT_ASSUMPTIONS = Path(__file__).resolve().parent.parent / "assumptions" / "nofire_brazil.yaml"
LABEL_WIDTH = 26
COLUMN_WIDTH = 22


def money(x: float) -> str:
    return f"R${x:,.0f}"


def pct(x: float) -> str:
    return f"{x:.0%}"


def segment_report(assumptions: Assumptions, key: str, strategies: list[str], runs: int, seed: int) -> str:
    seg = assumptions.segments[key]
    ranges = {s: assumptions.inputs_for(key, s) for s in strategies}
    base = {s: base_case(ranges[s]) for s in strategies}
    stats = {s: summarise(simulate(ranges[s], n=runs, seed=seed)) for s in strategies}

    def row(label, cell):
        return f"    {label:<{LABEL_WIDTH}}" + "".join(f"{cell(s):>{COLUMN_WIDTH}}" for s in strategies)

    lines = [
        f"{seg.label}  [{key}, {seg.delivery}]",
        f"    {'':<{LABEL_WIDTH}}" + "".join(f"{s:>{COLUMN_WIDTH}}" for s in strategies),
        "  Base case, per season",
        row("treatments", lambda s: f"{ranges[s]['applications_per_season'].base:g}"),
        row("fires met by a treatment", lambda s: pct(ranges[s]["timing_coverage"].base)),
        row("treated area", lambda s: f"{base[s]['treated_ha']:,.1f} ha"),
        row("cost", lambda s: money(base[s]["cost"])),
        row("avoided fire loss", lambda s: money(base[s]["avoided_loss"])),
        row("water saving", lambda s: money(base[s]["water_value"])),
        row("ROI", lambda s: pct(base[s]["roi"])),
        row("break-even product cost", lambda s: money(base[s]["breakeven_product_cost_per_ha"])),
        f"  Across {runs:,} runs",
        row("ROI P10 / median / P90", lambda s: " / ".join(pct(stats[s][q]) for q in ("roi_p10", "roi_median", "roi_p90"))),
        row("profitable", lambda s: pct(stats[s]["share_profitable"])),
        row("clears buyer's hurdle", lambda s: pct(stats[s]["share_clearing_hurdle"])),
        row("placeholder inputs", lambda s: f"{sum(ranges[s][n].status == 'placeholder' for n in INPUTS)} of {len(INPUTS)}"),
    ]
    for s in strategies:
        lines.append(f"  Inputs that move ROI most, {s} (each swung low to high, others at base)")
        for r in tornado(ranges[s]).head(5).itertuples():
            lines.append(f"    {r.input:<27} {pct(r.at_low):>7} to {pct(r.at_high):<7}  {r.status}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--assumptions", default=DEFAULT_ASSUMPTIONS, type=Path)
    parser.add_argument("--strategy", action="append", help="only show this strategy; repeat for more")
    parser.add_argument("--runs", default=10_000, type=int)
    parser.add_argument("--seed", default=0, type=int)
    args = parser.parse_args()

    assumptions = load(args.assumptions)
    strategies = args.strategy or list(assumptions.strategies)
    unknown = set(strategies) - set(assumptions.strategies)
    if unknown:
        parser.error(f"unknown strategy {', '.join(sorted(unknown))}; choose from {', '.join(assumptions.strategies)}")

    print(f"Per-farm ROI, preventive fire treatment ({assumptions.currency})")
    print("Break-even product cost is per hectare per application.\n")
    for s in strategies:
        print(f"  {s}: {assumptions.strategies[s]}")
    print()
    print("\n\n".join(segment_report(assumptions, key, strategies, args.runs, args.seed) for key in assumptions.segments))


if __name__ == "__main__":
    main()
