"""FSDS cross-check oracle: FSDS num facts against solver-parsed facts.

Facts join on (accession, concept, unit, period, segments). A custom
tag's version is its defining submission's adsh, so custom facts join
only within that accession; standard tags join by local concept name.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from edgar_sec.engine.xbrl.schema.models import XbrlFact


@dataclass(frozen=True, slots=True)
class FsdsFact:
    """One FSDS num row, with segments already in canonical form.

    The caller renders FSDS segments and solver dimensions into the
    same canonical string; this module compares them opaquely.
    """

    accession: str
    tag: str
    version: str
    unit: str
    period: str
    segments: str
    value: float | None


@dataclass(frozen=True, slots=True)
class FsdsTag:
    """One FSDS tag row: a (tag, version) pair and its custom flag."""

    tag: str
    version: str
    custom: bool


@dataclass(frozen=True, slots=True)
class FactKey:
    """Fact identity shared by both sides of the comparison."""

    accession: str
    concept: str
    unit: str
    period: str
    segments: str


@dataclass(frozen=True, slots=True)
class Divergence:
    """One key present on both sides whose values disagree."""

    key: FactKey
    fsds_values: tuple[float | None, ...]
    solver_values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class AccessionComparison:
    """Outcome-class counts for one accession of the panel."""

    accession: str
    agree: int = 0
    diverge: int = 0
    facts_only: int = 0
    solver_only: int = 0
    unresolved_tag: int = 0
    custom_version_mismatch: int = 0


@dataclass(frozen=True, slots=True)
class OracleReport:
    """The full panel outcome: per-accession classes and divergences."""

    per_accession: tuple[AccessionComparison, ...]
    divergences: tuple[Divergence, ...]

    @property
    def agree(self) -> int:
        """Panel-wide agreeing keys."""
        return sum(row.agree for row in self.per_accession)

    @property
    def diverge(self) -> int:
        """Panel-wide diverging keys."""
        return sum(row.diverge for row in self.per_accession)

    @property
    def facts_only(self) -> int:
        """Panel-wide keys only FSDS carries."""
        return sum(row.facts_only for row in self.per_accession)

    @property
    def solver_only(self) -> int:
        """Panel-wide keys only the solver carries."""
        return sum(row.solver_only for row in self.per_accession)


def fsds_fact_from_row(row: Mapping[str, str | None]) -> FsdsFact:
    """Map one loaded fsds_num row (all-text columns) to an FsdsFact."""
    raw_value = (row.get("value") or "").strip()
    return FsdsFact(
        accession=str(row.get("adsh") or "").strip(),
        tag=str(row.get("tag") or "").strip(),
        version=str(row.get("version") or "").strip(),
        unit=str(row.get("uom") or "").strip(),
        period=str(row.get("ddate") or "").strip(),
        segments=str(row.get("segments") or "").strip(),
        value=float(raw_value) if raw_value else None,
    )


def fsds_tag_from_row(row: Mapping[str, str | None]) -> FsdsTag:
    """Map one loaded fsds_tag row (all-text columns) to an FsdsTag."""
    return FsdsTag(
        tag=str(row.get("tag") or "").strip(),
        version=str(row.get("version") or "").strip(),
        custom=str(row.get("custom") or "").strip() == "1",
    )


def canonical_segments(dimensions: Mapping[str, str]) -> str:
    """Canonical segments identity for one solver fact's dimensions."""
    return ";".join(f"{axis}={member}" for axis, member in sorted(dimensions.items()))


def _solver_key(fact: XbrlFact) -> FactKey:
    period = fact.instant_date or fact.end_date or ""
    return FactKey(
        accession=str(fact.accession),
        concept=fact.concept_qname.rsplit(":", 1)[-1],
        unit=fact.unit or "",
        period=period.replace("-", ""),
        segments=canonical_segments(fact.dimensions),
    )


def _sorted_values(values: Iterable[float | None]) -> tuple[float | None, ...]:
    return tuple(sorted(values, key=lambda value: (value is None, value or 0.0)))


def compare_panel(
    fsds_facts: Iterable[FsdsFact],
    tag_definitions: Iterable[FsdsTag],
    solver_facts: Iterable[XbrlFact],
) -> OracleReport:
    """Compare one panel of FSDS facts against solver-parsed facts."""
    definitions = {(tag.tag, tag.version): tag for tag in tag_definitions}
    counts: dict[str, dict[str, int]] = {}

    def bump(accession: str, field: str) -> None:
        row = counts.setdefault(accession, {})
        row[field] = row.get(field, 0) + 1

    fsds_by_key: dict[FactKey, list[float | None]] = {}
    for fact in fsds_facts:
        definition = definitions.get((fact.tag, fact.version))
        if definition is None:
            bump(fact.accession, "unresolved_tag")
            continue
        if definition.custom and fact.version != fact.accession:
            bump(fact.accession, "custom_version_mismatch")
            continue
        key = FactKey(
            accession=fact.accession,
            concept=fact.tag,
            unit=fact.unit,
            period=fact.period,
            segments=fact.segments,
        )
        fsds_by_key.setdefault(key, []).append(fact.value)

    solver_by_key: dict[FactKey, list[float]] = {}
    for fact in solver_facts:
        if not isinstance(fact.value, (int, float)):
            continue
        solver_by_key.setdefault(_solver_key(fact), []).append(float(fact.value))

    divergences: list[Divergence] = []
    all_keys = sorted(
        set(fsds_by_key) | set(solver_by_key),
        key=lambda key: (
            key.accession,
            key.concept,
            key.unit,
            key.period,
            key.segments,
        ),
    )
    for key in all_keys:
        fsds_values = _sorted_values(fsds_by_key.get(key, []))
        solver_values = _sorted_values(solver_by_key.get(key, []))
        if key not in solver_by_key:
            bump(key.accession, "facts_only")
        elif key not in fsds_by_key:
            bump(key.accession, "solver_only")
        elif fsds_values == solver_values:
            bump(key.accession, "agree")
        else:
            bump(key.accession, "diverge")
            divergences.append(
                Divergence(
                    key=key,
                    fsds_values=fsds_values,
                    solver_values=tuple(
                        value for value in solver_values if value is not None
                    ),
                )
            )
    per_accession = tuple(
        AccessionComparison(accession=accession, **counts[accession])
        for accession in sorted(counts)
    )
    return OracleReport(per_accession=per_accession, divergences=tuple(divergences))


__all__ = [
    "AccessionComparison",
    "Divergence",
    "FactKey",
    "FsdsFact",
    "FsdsTag",
    "OracleReport",
    "canonical_segments",
    "compare_panel",
    "fsds_fact_from_row",
    "fsds_tag_from_row",
]
