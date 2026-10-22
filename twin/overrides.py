"""Fix chosen inputs at single values for a what-if, as the coaching app's controls and `--price` do.

Anything not named keeps its range, so Monte Carlo runs still vary it.
"""

from dataclasses import replace

from twin.assumptions import Assumptions, Range


def fixed(value: float, note: str = "Set for this what-if") -> Range:
    return Range(value, value, value, "scenario", note)


def _merge(current: dict[str, Range], changes: dict[str, float] | None, section: str) -> dict[str, Range]:
    if not changes:
        return current
    unknown = set(changes) - set(current)
    if unknown:
        raise KeyError(f"{section} has no input named {', '.join(sorted(unknown))}")
    return {**current, **{name: fixed(value) for name, value in changes.items()}}


def override(assumptions: Assumptions, *, product: dict[str, float] | None = None, buyer: dict[str, float] | None = None,
             population: dict[str, float] | None = None, adoption_rates: dict[str, float] | None = None,
             coop_member_share: dict[str, float] | None = None) -> Assumptions:
    """A copy of the assumptions with the named inputs fixed at the given values."""
    a = replace(
        assumptions,
        product=_merge(assumptions.product, product, "product"),
        buyer=_merge(assumptions.buyer, buyer, "buyer"),
        population=_merge(assumptions.population, population, "population"),
    )
    if adoption_rates or coop_member_share:
        a = replace(a, adoption=replace(
            a.adoption,
            rates=_merge(a.adoption.rates, adoption_rates, "adoption"),
            coop_member_share=_merge(a.adoption.coop_member_share, coop_member_share, "adoption.coop_member_share"),
        ))
    return a
