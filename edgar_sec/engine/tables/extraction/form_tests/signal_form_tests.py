"""Signal form-test evaluators: the spec-driven generic kinds.

Row-bound, signature-absence, and placement evaluators read
their parameters from form_signal_specs and judge table shape
and filing placement rather than family arithmetic.
"""

from __future__ import annotations

from functools import lru_cache

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.form_specs.form_signal_specs import (
    ORIENT_EITHER_AXIS,
    PLACEMENT_SPECS_BY_TEST_ID,
    PRED_DEEP_NOTES,
    PRED_ISOLATED_DEEP_NOTES,
    PRED_NOTES_ISOLATED,
    ROW_BOUND_SPECS_BY_TEST_ID,
    SIGNATURE_ABSENCE_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
    FormTestSpec,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.text.placement import (
    REGION_NOTES,
    PlacementFacts,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable


def _evaluate_row_bound(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    params = ROW_BOUND_SPECS_BY_TEST_ID[spec.test_id]
    grid_rows = table.context.grid_rows or len(table.rows)
    if grid_rows <= 0:
        return FormTestOutcome(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "no grid rows",
        )
    inside = params.min_rows <= grid_rows <= params.max_rows
    axis = "rows"
    if not inside and params.orientation == ORIENT_EITHER_AXIS:
        columns = table.context.max_row_cells or len(table.periods) + 1
        inside = params.min_rows <= columns <= params.max_rows
        axis = "columns" if inside else "rows"
    detail = (
        f"grid {axis} within [{params.min_rows}, {params.max_rows}]"
        if inside
        else f"grid rows {grid_rows} outside [{params.min_rows}, {params.max_rows}]"
    )
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        inside,
        True,
        0,
        spec.points,
        detail,
    )


@lru_cache(maxsize=None)
def _signatures_index(signatures: tuple[str, ...]) -> TermIndex:
    """One phrase-kind index over an absence spec's signature
    labels, valued by the label itself."""
    return TermIndex([TermEntry(term, "signature", value=term) for term in signatures])


def _evaluate_absence(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    params = SIGNATURE_ABSENCE_SPECS_BY_TEST_ID[spec.test_id]
    labels = [normalize_text(row.label) for row in table.rows if row.label]
    if not labels:
        return FormTestOutcome(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "no labels",
        )
    signatures = [normalize_text(term) for term in params.signature_labels]
    signature_index = _signatures_index(tuple(signatures))
    present_values: set[str] = set()
    for label in labels:
        present_values |= set(signature_index.scan(label).get("signature", frozenset()))
    present = next(
        (term for term in signatures if term in present_values),
        None,
    )
    detail = (
        f"signature label present: {present}"
        if present
        else "signature vocabulary wholly absent"
    )
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        present is not None,
        True,
        0,
        spec.points,
        detail,
    )


def _placement_fired(predicate: str, facts: PlacementFacts) -> bool:
    if predicate == PRED_NOTES_ISOLATED:
        return facts.region == REGION_NOTES and facts.isolated
    if predicate == PRED_DEEP_NOTES:
        return facts.deep_notes
    if predicate == PRED_ISOLATED_DEEP_NOTES:
        return facts.isolated and facts.deep_notes
    return False


def _evaluate_placement(
    table: TypedTable, spec: FormTestSpec, facts: PlacementFacts | None
) -> FormTestOutcome:
    if facts is None:
        return FormTestOutcome(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "placement unstamped",
        )
    params = PLACEMENT_SPECS_BY_TEST_ID[spec.test_id]
    fired = _placement_fired(params.predicate, facts)
    detail = (
        f"placement conjunction {params.predicate} fired"
        if fired
        else f"placement conjunction {params.predicate} clear"
    )
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not fired,
        True,
        0,
        spec.points,
        detail,
    )
