"""Composition-twin evaluator for the form-test stage.

Reads composition form only: a table enumerating the family's
component classes with amounts per class passes; totals-only
summaries and single-line forms fail.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.foundation.text.dates import YEAR_TOKEN_SEARCH_RE
from edgar_sec.engine.tables.extraction.core.normalize import normalize_text
from edgar_sec.engine.tables.extraction.form_specs.composition_specs import (
    COMPOSITION_SPECS_BY_FAMILY,
    CompositionSpec,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable


@dataclass(frozen=True, slots=True)
class CompositionResult:
    """One composition evaluation; the stage outcome's shape."""

    family: str
    test_id: str
    kind: str
    passed: bool
    evaluable: bool
    columns_closed: int
    points: float
    detail: str


def _amount_bearing(cells: tuple[str, ...]) -> bool:
    return any(any(ch.isdigit() for ch in cell) and "%" not in cell for cell in cells)


def _is_total(spec: CompositionSpec, stub: str) -> bool:
    return any(term in stub for term in spec.total_terms)


def _group_hits(spec: CompositionSpec, texts: tuple[str, ...]) -> int:
    return sum(
        1
        for group in spec.stub_groups
        if any(term in text for term in group for text in texts)
    )


def _header_text(table: TypedTable) -> str:
    parts = [title for title in table.caption.titles]
    for row in table.context.rows[: table.header_rows]:
        parts.extend(cell for cell in row if cell)
    return normalize_text(" ".join(parts))


def _passes(spec: CompositionSpec, header: str, table: TypedTable) -> tuple[bool, int]:
    """The spec's declared reading over one typed table."""
    class_rows = [
        row
        for row in table.rows
        if _amount_bearing(row.raw[1:])
        and not _is_total(spec, normalize_text(row.label))
    ]
    if len(class_rows) < spec.min_class_rows:
        return False, 0
    if spec.orientation == "columns":
        hits = _group_hits(spec, (header,))
        return hits >= spec.min_stub_groups, hits
    stubs = tuple(normalize_text(row.label) for row in class_rows)
    hits = _group_hits(spec, stubs)
    if hits < spec.min_stub_groups:
        return False, hits
    anywhere = " ".join((header, *stubs))
    column_hits = sum(
        1 for group in spec.column_groups if any(term in anywhere for term in group)
    )
    if column_hits >= spec.min_column_groups:
        return True, hits
    years = set(YEAR_TOKEN_SEARCH_RE.findall(header))
    return spec.period_columns and len(years) >= 2, hits


def evaluate_composition(table: TypedTable, spec: FormTestSpec) -> CompositionResult:
    """Evaluate one table against one composition-twin spec."""
    params = COMPOSITION_SPECS_BY_FAMILY.get(spec.family)
    if params is None:
        return CompositionResult(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "no composition parameters for family",
        )
    passed, hits = _passes(params, _header_text(table), table)
    return CompositionResult(
        spec.family,
        spec.test_id,
        spec.kind,
        passed,
        True,
        hits,
        spec.points,
        f"composition groups hit: {hits}",
    )
