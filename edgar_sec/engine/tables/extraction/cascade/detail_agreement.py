"""Filing-level detail agreement: a breakdown claimed by its host.

A detail table's components close to one line of a primary
statement in the same filing; that value agreement is the priced
separator claiming the table for the host family (Step 3)."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.typed_rows import RowKind, TypedTable

DETAIL_AGREEMENT_POINTS = 3.0
# A detail seat is an attributed claim, not evidence seating:
# the agreement points alone clear this floor, reached exactly
# when the host's own scored evidence is non-negative.
DETAIL_AGREEMENT_FLOOR = 3.0
_AGREEMENT_REL_TOLERANCE = 0.005
_AGREEMENT_MIN_VALUE = 100.0
_MIN_COMPONENTS = 2


@dataclass(frozen=True, slots=True)
class DetailAgreement:
    """One unambiguous agreement: host family and the line's label."""

    host_family: str
    host_label: str


def _agrees(computed: float, target: float) -> bool:
    return abs(target) >= _AGREEMENT_MIN_VALUE and abs(
        computed - target
    ) <= _AGREEMENT_REL_TOLERANCE * abs(target)


def _closures(table: TypedTable) -> list[float]:
    """Per-column totals the table's own components close to.
    A stated total must equal its components' sum; without one,
    a column needs at least three components to state a sum."""
    width = max((len(row.values) for row in table.rows), default=0)
    totals = [row for row in table.rows if row.kind == RowKind.TOTAL]
    closed: list[float] = []
    for column in range(width):
        components = [
            row.values[column]
            for row in table.rows
            if row.kind == RowKind.DATA
            and column < len(row.values)
            and row.values[column] is not None
        ]
        if len(components) < _MIN_COMPONENTS:
            continue
        summed = sum(float(value) for value in components)
        stated = next(
            (
                float(row.values[column])
                for row in totals
                if column < len(row.values) and row.values[column] is not None
            ),
            None,
        )
        if stated is not None:
            if _agrees(summed, stated):
                closed.append(stated)
        elif len(components) > _MIN_COMPONENTS:
            closed.append(summed)
    return closed


def _host_lines(table: TypedTable) -> list[tuple[str, float]]:
    lines = []
    for row in table.rows:
        if row.kind in (RowKind.SECTION, RowKind.PARENTHETICAL):
            continue
        for value in row.values:
            if value is not None:
                lines.append((normalize_text(row.label), float(value)))
    return lines


def find_detail_agreement(
    table: TypedTable,
    hosts: list[tuple[str, TypedTable]],
) -> DetailAgreement | None:
    """The one host family this table's closures agree with, if any.
    Agreement with lines of two host families is ambiguous and
    claims nothing."""
    closed = _closures(table)
    if not closed:
        return None
    matched: dict[str, str] = {}
    for family, host in hosts:
        for label, value in _host_lines(host):
            if any(_agrees(total, value) for total in closed):
                matched.setdefault(family, label)
    if len(matched) != 1:
        return None
    family, label = next(iter(matched.items()))
    return DetailAgreement(family, label)
