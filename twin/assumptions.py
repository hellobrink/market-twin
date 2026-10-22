"""Load assumption ranges from YAML into typed objects."""

from dataclasses import dataclass
from pathlib import Path

import yaml

STATUSES = {"placeholder", "pilot", "interview", "public"}


@dataclass(frozen=True)
class Range:
    """One uncertain input: a low, base and high value plus where it came from."""

    low: float
    base: float
    high: float
    status: str
    note: str = ""

    def __post_init__(self):
        if not self.low <= self.base <= self.high:
            raise ValueError(f"range must satisfy low <= base <= high, got {self.low}, {self.base}, {self.high}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}; use one of {sorted(STATUSES)}")


@dataclass(frozen=True)
class Segment:
    key: str
    label: str
    delivery: str
    params: dict[str, Range]


@dataclass(frozen=True)
class Assumptions:
    currency: str
    product: dict[str, Range]
    delivery: dict[str, dict[str, Range]]
    buyer: dict[str, Range]
    segments: dict[str, Segment]

    def inputs_for(self, segment_key: str) -> dict[str, Range]:
        """Every range that applies to one segment, as a flat name -> Range map."""
        seg = self.segments[segment_key]
        return {**self.product, **self.delivery[seg.delivery], **self.buyer, **seg.params}


def _ranges(raw: dict) -> dict[str, Range]:
    return {name: Range(**spec) for name, spec in raw.items()}


def load(path: str | Path) -> Assumptions:
    raw = yaml.safe_load(Path(path).read_text())
    delivery = {mode: _ranges(spec) for mode, spec in raw["delivery"].items()}
    segments = {}
    for key, spec in raw["segments"].items():
        spec = dict(spec)
        label = spec.pop("label")
        mode = spec.pop("delivery")
        if mode not in delivery:
            raise ValueError(f"segment {key!r} uses unknown delivery mode {mode!r}")
        segments[key] = Segment(key=key, label=label, delivery=mode, params=_ranges(spec))
    return Assumptions(
        currency=raw["currency"],
        product=_ranges(raw["product"]),
        delivery=delivery,
        buyer=_ranges(raw["buyer"]),
        segments=segments,
    )
