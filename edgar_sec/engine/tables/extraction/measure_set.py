"""Measure-set evaluator for the form-test stage.

A filed form is a set of named measures, carried as columns or as
rows; the test counts the spec's priced groups present in the
table's stub, header and caption text, orientation-free."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_test_specs import FormTestSpec
from edgar_sec.engine.tables.extraction.measure_set_specs import (
    MEASURE_SET_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable


@dataclass(frozen=True, slots=True)
class MeasureSetResult:
    """One measure-set evaluation: admission, evaluability, why."""

    admitted: bool
    evaluable: bool
    detail: str


def _texts(table: TypedTable) -> list[str]:
    """The match universe: row labels, header cells and joins, titles."""
    texts = [normalize_text(row.label) for row in table.rows if row.label]
    texts.extend(normalize_text(title) for title in table.caption.titles)
    start = table.caption.consumed_rows
    zone = table.context.rows[start : start + table.header_rows + 2]
    width = max((len(row) for row in zone), default=0)
    for row in zone:
        texts.extend(normalize_text(cell) for cell in row if cell)
    for column in range(width):
        joined = " ".join(
            normalize_text(row[column])
            for row in zone
            if column < len(row) and normalize_text(row[column])
        )
        if joined:
            texts.append(joined)
    return [text for text in texts if text]


def _present(texts: list[str], phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for text in texts for phrase in phrases)


def evaluate_measure_set(table: TypedTable, spec: FormTestSpec) -> MeasureSetResult:
    """Evaluate one table against one measure-set spec."""
    params = MEASURE_SET_SPECS_BY_TEST_ID[spec.test_id]
    texts = _texts(table)
    if not texts:
        return MeasureSetResult(False, False, "no stub or header text")
    refused = next(
        (term for term in params.refused_terms if _present(texts, (term,))),
        None,
    )
    if refused is not None:
        return MeasureSetResult(False, True, f"refused term present: {refused}")
    missing = next(
        (term for term in params.subject_terms if not _present(texts, (term,))),
        None,
    )
    if missing is not None:
        return MeasureSetResult(False, True, f"subject absent: {missing}")
    hits = sum(1 for group in params.groups if _present(texts, group))
    admitted = hits >= params.min_groups
    detail = (
        f"{hits} of {len(params.groups)} measure groups present"
        f" (needs {params.min_groups})"
    )
    return MeasureSetResult(admitted, True, detail)
