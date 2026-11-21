"""Step 2 form signals: row bound, signature absence, placement.
Each kind passes and fails on synthetic member/imposter forms;
placement is unevaluable until the caller stamps filing facts."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.classify import (
    candidate_scores,
    classify_filing,
)
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.core.placement import placement_facts
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)


def _table(rows: tuple[tuple[str, ...], ...], **context_kwargs: object) -> TypedTable:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows,
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    return structure_table(TableContext(geometry=geometry, **context_kwargs))


def _outcome(table: TypedTable, test_id: str, **kwargs: object):
    return next(o for o in evaluate_form_tests(table, **kwargs) if o.test_id == test_id)


def _balance_sheet_rows(count: int) -> tuple[tuple[str, ...], ...]:
    return tuple((f"Asset line {i}", "10") for i in range(count))


def test_row_bound_passes_inside_the_member_envelope() -> None:
    table = _table(_balance_sheet_rows(30))
    assert _outcome(table, "balance_sheet_row_bound").passed


def test_row_bound_fails_on_the_short_imposter_form() -> None:
    table = _table(_balance_sheet_rows(11))
    outcome = _outcome(table, "balance_sheet_row_bound")
    assert not outcome.passed and outcome.evaluable


def test_row_bound_either_axis_reads_the_transposed_seating() -> None:
    rows = (("Balance at beginning of period",) + tuple("1" for _ in range(12)),)
    table = _table(rows, grid_rows=3, max_row_cells=13)
    assert _outcome(table, "stock_comp_rollforward_row_bound").passed
    fixed = _table(rows, grid_rows=3, max_row_cells=13)
    assert not _outcome(fixed, "balance_sheet_row_bound").passed


def test_signature_absence_passes_with_a_signature_label() -> None:
    table = _table(
        (
            ("Accumulated depreciation", "(150)"),
            ("Land", "100"),
            ("Building", "200"),
        )
    )
    assert _outcome(table, "ppe_signature_absence").passed


def test_signature_absence_fails_when_vocabulary_wholly_absent() -> None:
    table = _table((("Revenue", "100"), ("Cost of revenue", "60")))
    outcome = _outcome(table, "ppe_signature_absence")
    assert not outcome.passed and outcome.evaluable


def test_signature_absence_unevaluable_without_labels() -> None:
    table = _table((("", "100"), ("", "60")))
    outcome = _outcome(table, "ppe_signature_absence")
    assert not outcome.evaluable


def test_placement_unstamped_is_unevaluable() -> None:
    table = _table(_balance_sheet_rows(30))
    outcome = _outcome(table, "balance_sheet_placement")
    assert not outcome.evaluable and outcome.detail == "placement unstamped"


def test_placement_fails_the_isolated_notes_imposter() -> None:
    families = ("balance_sheet", "cash_flow") + ("other",) * 6 + ("ppe",)
    facts = placement_facts(families, 8)
    table = _table(_balance_sheet_rows(30))
    outcome = _outcome(table, "balance_sheet_placement", placement=facts)
    assert not outcome.passed and outcome.evaluable


def test_placement_passes_the_seated_statement() -> None:
    families = ("balance_sheet", "cash_flow") + ("other",) * 6
    facts = placement_facts(families, 0)
    table = _table(_balance_sheet_rows(30))
    outcome = _outcome(table, "balance_sheet_placement", placement=facts)
    assert outcome.passed


def test_placement_deep_notes_fail_for_comprehensive_income() -> None:
    families = ("balance_sheet", "cash_flow") + ("other",) * 20
    facts = placement_facts(families, 17)
    table = _table(_balance_sheet_rows(10))
    outcome = _outcome(table, "comprehensive_income_placement", placement=facts)
    assert not outcome.passed


_PERIODS = ("", "December 31, 2024", "December 31, 2023")
_BS_HEAD_ROWS = (
    ("ACME CORP",),
    ("Consolidated Balance Sheets",),
    _PERIODS,
    ("Assets", "", ""),
    ("Cash and cash equivalents", "100", "90"),
    ("Total current assets", "100", "90"),
    ("Total assets", "100", "90"),
)
_THIN_ROWS = (
    _PERIODS,
    ("Total assets", "100", "90"),
)
_QUIET_ROWS = (
    _PERIODS,
    ("Other liabilities", "10", "9"),
    ("Accrued expenses", "5", "4"),
)
_BS_LOOKALIKE_ROWS = (
    _PERIODS,
    ("Total assets", "100", "90"),
    ("Total liabilities", "60", "50"),
)


def test_placement_pass_leaves_filing_scores_untouched() -> None:
    head = _table(_BS_HEAD_ROWS)
    fragment = _table(_THIN_ROWS)
    _, scores = classify_filing([head, fragment])
    expected = {
        family: score for family, (score, _) in candidate_scores(fragment).items()
    }
    assert scores[1] == expected


def test_placement_fire_zeroes_the_family_candidacy() -> None:
    tables = [_table(_BS_HEAD_ROWS)]
    tables += [_table(_QUIET_ROWS) for _ in range(3)]
    lookalike = _table(_BS_LOOKALIKE_ROWS)
    tables.append(lookalike)
    assert candidate_scores(lookalike)["balance_sheet"][0] > 0
    _, scores = classify_filing(tables)
    assert scores[4]["balance_sheet"] == 0.0
