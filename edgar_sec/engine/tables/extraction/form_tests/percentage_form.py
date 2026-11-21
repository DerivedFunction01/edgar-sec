"""Percentage-form evaluator for the form-test stage.

Reads arithmetic form only: a percentage anchor row plus its
percentage adjustments must close to the percentage total row
per column, within the spec's threshold in percentage points.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.engine.tables.extraction.core.normalize import normalize_text
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.form_specs.percentage_form_specs import (
    PERCENTAGE_SPECS_BY_FAMILY,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable


@dataclass(frozen=True, slots=True)
class PercentageFormResult:
    """One percentage-form evaluation; the stage outcome's shape."""

    family: str
    test_id: str
    kind: str
    passed: bool
    evaluable: bool
    columns_closed: int
    points: float
    detail: str


def _matches(label: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in label for pattern in patterns)


def _percent_values(raw: tuple[str, ...]) -> dict[int, float]:
    """A raw row's percentage values, keyed by raw column index."""
    values: dict[int, float] = {}
    cells = raw[1:]
    for index, cell in enumerate(cells):
        value = clean_numeric(cell)
        if value is None:
            continue
        marked = "%" in cell or "percent" in cell.lower()
        if not marked and index + 1 < len(cells):
            marked = cells[index + 1].strip() in ("%", "percent")
        if marked:
            values[index + 1] = float(value)
    return values


def evaluate_percentage_form(
    table: TypedTable, spec: FormTestSpec
) -> PercentageFormResult:
    """Evaluate one table against one percentage-form spec."""
    params = PERCENTAGE_SPECS_BY_FAMILY.get(spec.family)
    if params is None:
        return PercentageFormResult(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "no percentage parameters for family",
        )
    labels = [normalize_text(row.label) for row in table.rows]
    anchors = [
        i for i, label in enumerate(labels) if _matches(label, params.anchor_tokens)
    ]
    totals = [
        i for i, label in enumerate(labels) if _matches(label, params.total_tokens)
    ]
    if not anchors or not totals:
        return PercentageFormResult(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "anchors absent",
        )
    anchor_at = anchors[0]
    total_at = totals[-1]
    if total_at <= anchor_at:
        return PercentageFormResult(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            True,
            0,
            spec.points,
            "total row does not follow the anchor row",
        )
    block = table.rows[anchor_at : total_at + 1]
    movements = len(block) - 2
    if movements < params.min_adjustments:
        return PercentageFormResult(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            True,
            0,
            spec.points,
            "no adjustment row between anchor and total",
        )
    per_row = [_percent_values(row.raw) for row in block]
    if any(not values for values in per_row):
        return PercentageFormResult(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            True,
            0,
            spec.points,
            "a block row carries no percentage value",
        )
    columns = set(per_row[0])
    for values in per_row[1:]:
        columns &= set(values)
    threshold = params.closure_tolerance
    closed = sum(
        1
        for column in columns
        if abs(sum(values[column] for values in per_row[:-1]) - per_row[-1][column])
        <= threshold
    )
    passed = closed >= params.min_columns and closed == len(columns)
    detail = (
        f"percentage form closed in {closed} column(s)"
        if passed
        else f"percentage form open ({closed} of {len(columns)} column(s) closed)"
    )
    return PercentageFormResult(
        spec.family,
        spec.test_id,
        spec.kind,
        passed,
        True,
        closed,
        spec.points,
        detail,
    )
