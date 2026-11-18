"""Verdict finishing: flavor, kind, and re-arbitration."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.classification import (
    Classification,
    Evidence,
    TableKind,
)
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.registry import (
    ASSIGNMENT_FLOOR,
    CORE_FAMILIES,
    FAMILY_PRIORITY,
    RESIDUAL_FAMILY,
)
from edgar_sec.engine.tables.extraction.typed_rows import RowKind, TypedTable


def _flavor(family: str, labels: list[str], table: TypedTable) -> str | None:
    label_set = {label for label in labels if label}

    def has(*needles: str) -> bool:
        return any(needle in label for label in label_set for needle in needles)

    if family == "balance_sheet":
        if has("current assets") and has("current liabilities"):
            return "classified"
        return "unclassified"
    if family == "income_statement":
        if has("gross profit", "gross margin"):
            return "multi_step"
        return "single_step"
    if family == "cash_flow":
        if has("adjustments to reconcile"):
            return "indirect"
        valued = [
            normalize_text(row.label)
            for row in table.rows
            if any(value is not None for value in row.values)
        ]
        if valued and valued[0].startswith(("net income", "net loss")):
            return "indirect"
        return None
    return None


def _kind(family: str, table: TypedTable) -> TableKind:
    rows = table.rows
    if rows:
        parenthetical = sum(1 for row in rows if row.kind is RowKind.PARENTHETICAL)
        if parenthetical * 2 >= len(rows):
            return TableKind.PARENTHETICAL
    if family in CORE_FAMILIES:
        return TableKind.STATEMENT
    if table.context.note is not None:
        return TableKind.NOTE_DETAIL
    return TableKind.STATEMENT


def finish(
    family: str,
    tier: str,
    score: float,
    evidence: list[Evidence],
    labels: list[str],
    table: TypedTable,
) -> Classification:
    return Classification(
        family=family,
        flavor=_flavor(family, labels, table),
        kind=_kind(family, table),
        tier=tier,
        score=score,
        evidence=tuple(evidence),
    )


def context_base(table: TypedTable) -> list[Evidence]:
    section = table.context.section
    return [
        Evidence(
            "context",
            f"section={section.item if section else None} "
            f"note={table.context.note is not None}",
            0.0,
        )
    ]


def refinish(
    table: TypedTable,
    scores: dict[str, float],
    evidence: dict[str, tuple[Evidence, ...]],
    marker: Evidence,
    floor: float = ASSIGNMENT_FLOOR,
) -> Classification:
    """Re-arbitrate one table over adjusted filing-level scores."""
    labels = [normalize_text(row.label) for row in table.rows]
    winner = min(
        scores,
        key=lambda family: (-scores[family], FAMILY_PRIORITY.index(family)),
    )
    score = scores[winner]
    base = context_base(table)
    if score >= floor:
        trail = base + list(evidence.get(winner, ())) + [marker]
        return finish(winner, "evidence", score, trail, labels, table)
    trail = base + [
        Evidence(
            "residual",
            f"best {winner} at {score:.2f} below floor {floor}",
            0.0,
        ),
        marker,
    ]
    return finish(RESIDUAL_FAMILY, "residual", score, trail, labels, table)
