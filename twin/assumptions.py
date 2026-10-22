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
    strategies: dict[str, dict[str, Range]]


@dataclass(frozen=True)
class FireScenario:
    """How farm fire risk is set: MapBiomas burn rates averaged over a span of years,
    or a weighted mix of other scenarios (`mix`), such as mostly normal years with an
    occasional severe one."""

    name: str
    description: str
    first: int | None = None
    last: int | None = None
    mix: dict[str, float] | None = None

    def label(self) -> str:
        if self.mix:
            return ", ".join(f"{share:.0%} {name}" for name, share in self.mix.items())
        return f"{self.first}-{self.last}"


@dataclass(frozen=True)
class AdoptionAssumptions:
    start_year: int
    seasons: int
    runs: int
    last_severe_year: int
    rates: dict[str, Range]
    coop_member_share: dict[str, Range]


@dataclass(frozen=True)
class Assumptions:
    currency: str
    strategies: dict[str, str]
    product: dict[str, Range]
    delivery: dict[str, dict[str, Range]]
    buyer: dict[str, Range]
    segments: dict[str, Segment]
    population: dict[str, Range]
    fire_scenarios: dict[str, FireScenario]
    adoption: AdoptionAssumptions | None = None

    def inputs_for(self, segment_key: str, strategy: str) -> dict[str, Range]:
        """Every range that applies to one segment under one treatment strategy, as a flat name -> Range map."""
        seg = self.segments[segment_key]
        return {**self.product, **self.delivery[seg.delivery], **self.buyer, **seg.params, **seg.strategies[strategy]}


def _ranges(raw: dict) -> dict[str, Range]:
    return {name: Range(**spec) for name, spec in raw.items()}


def load(path: str | Path) -> Assumptions:
    raw = yaml.safe_load(Path(path).read_text())
    strategies = raw["strategies"]
    delivery = {mode: _ranges(spec) for mode, spec in raw["delivery"].items()}
    segments = {}
    for key, spec in raw["segments"].items():
        spec = dict(spec)
        label = spec.pop("label")
        mode = spec.pop("delivery")
        if mode not in delivery:
            raise ValueError(f"segment {key!r} uses unknown delivery mode {mode!r}")
        seg_strategies = {name: _ranges(s) for name, s in spec.pop("strategies").items()}
        if set(seg_strategies) != set(strategies):
            raise ValueError(f"segment {key!r} must give values for strategies {sorted(strategies)}, got {sorted(seg_strategies)}")
        segments[key] = Segment(key=key, label=label, delivery=mode, params=_ranges(spec), strategies=seg_strategies)
    return Assumptions(
        currency=raw["currency"],
        strategies=strategies,
        product=_ranges(raw["product"]),
        delivery=delivery,
        buyer=_ranges(raw["buyer"]),
        segments=segments,
        population=_ranges(raw.get("population", {})),
        fire_scenarios=_fire_scenarios(raw.get("fire_scenarios", {})),
        adoption=_adoption(raw["adoption"], segments) if "adoption" in raw else None,
    )


def _adoption(raw: dict, segments: dict[str, Segment]) -> AdoptionAssumptions:
    raw = dict(raw)
    fixed = {key: int(raw.pop(key)) for key in ("start_year", "seasons", "runs", "last_severe_year")}
    coop = _ranges(raw.pop("coop_member_share"))
    if set(coop) != set(segments):
        raise ValueError(f"adoption.coop_member_share must cover segments {sorted(segments)}, got {sorted(coop)}")
    return AdoptionAssumptions(**fixed, rates=_ranges(raw), coop_member_share=coop)


def _fire_scenarios(raw: dict) -> dict[str, FireScenario]:
    scenarios = {name: _fire_scenario(name, spec) for name, spec in raw.items()}
    for s in scenarios.values():
        for part in (s.mix or {}):
            if part not in scenarios or scenarios[part].mix:
                raise ValueError(f"fire scenario {s.name!r} mixes {part!r}, which must be a year-based scenario")
    return scenarios


def _fire_scenario(name: str, spec: dict) -> FireScenario:
    description = spec.get("description", "")
    if "mix" in spec:
        mix = {k: float(v) for k, v in spec["mix"].items()}
        if abs(sum(mix.values()) - 1) > 1e-9:
            raise ValueError(f"fire scenario {name!r} mix must add up to 1, got {sum(mix.values())}")
        return FireScenario(name=name, description=description, mix=mix)
    first, last = (int(y) for y in str(spec["years"]).split("-"))
    if first > last:
        raise ValueError(f"fire scenario {name!r} has years {spec['years']!r}; the first year must come first")
    return FireScenario(name=name, description=description, first=first, last=last)
