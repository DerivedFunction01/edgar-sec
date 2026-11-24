"""Warranty-evidence gate: registry data, specimen shapes, seat."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_WARRANTY_EVIDENCE,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.registry import FAMILY_PRIORITY
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.warranty_evidence import (
    WarrantyText,
    evaluate_form_test_warranty,
    evaluate_warranty_evidence,
)
from edgar_sec.engine.tables.extraction.specs.families.warranty_specs import (
    WARRANTY_EVIDENCE_SPECS,
    WARRANTY_EVIDENCE_SPECS_BY_TEST_ID,
)

SPEC = WARRANTY_EVIDENCE_SPECS["warranty"]

_WALK = (
    ("Balance at beginning of period", "$ 10,000"),
    ("Accruals for warranties issued", "2,000"),
    ("Settlements", "(3,000)"),
    ("Balance at end of period", "$ 9,000"),
)

_TRANSPOSED = (
    ("", "December 31, 2023", "December 31, 2024"),
    ("Accrued warranty liability", "1,000", "1,200"),
    ("Accruals for warranties issued", "300", "350"),
)


def _table(
    rows: tuple[tuple[str, ...], ...],
    caption_stack: tuple[str, ...] = (),
    prose_before: str = "",
):
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
    context = TableContext(
        geometry=geometry, caption_stack=caption_stack, prose_before=prose_before
    )
    return structure_table(context)


def _verdict(
    rows: tuple[tuple[str, ...], ...],
    caption_stack: tuple[str, ...] = (),
    prose_before: str = "",
):
    spec = next(s for s in FORM_TEST_SPECS if s.family == "warranty")
    return evaluate_form_test_warranty(_table(rows, caption_stack, prose_before), spec)


def test_gate_is_declared_as_form_test_data():
    spec = next(s for s in FORM_TEST_SPECS if s.family == "warranty")
    assert spec.kind == TEST_WARRANTY_EVIDENCE
    assert spec.test_id == "warranty_rollforward_evidence"
    assert spec.points == 3.0
    assert WARRANTY_EVIDENCE_SPECS_BY_TEST_ID[spec.test_id] is SPEC
    profile = profile_for("warranty")
    assert profile is not None
    assert TEST_WARRANTY_EVIDENCE in profile.form_tests
    assert "warranty" in FAMILY_PRIORITY


def test_canonical_walk_is_admitted():
    result = _verdict(_WALK, caption_stack=("Product Warranty Liability",))
    assert result.admitted
    assert "word pair" in result.detail
    assert result.detail.endswith("movements accrual, claims")


def test_prose_tail_subject_is_admitted():
    prose = ("Detail follows in the notes to the statements. " * 30) + (
        "The balances relate to warranty obligations."
    )
    rows = (
        ("Balance at beginning of period", "100"),
        ("Additions", "10"),
        ("Payments", "(5)"),
        ("Balance at end of period", "105"),
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert result.admitted


def test_first_line_subject_is_admitted():
    rows = (
        ("Warranty liability activity", ""),
        ("Balance at beginning of period", "100"),
        ("Additions", "10"),
        ("Balance at end of period", "110"),
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",))
    assert result.admitted


def test_single_movement_type_is_admitted():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Settlements", "(40)"),
        ("Balance at end of period", "60"),
    )
    result = _verdict(rows, caption_stack=("Warranty Reserve",))
    assert result.admitted
    assert result.detail.endswith("movements claims")


def test_expenditures_dialect_is_admitted():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Expenditures", "5"),
        ("Balance at end of period", "105"),
    )
    result = _verdict(rows, caption_stack=("Warranty Reserve",))
    assert result.admitted
    assert result.detail.endswith("movements claims")


def test_charged_dialect_is_admitted():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Charged to expense", "5"),
        ("Balance at end of period", "105"),
    )
    result = _verdict(rows, caption_stack=("Warranty Reserve",))
    assert result.admitted
    assert result.detail.endswith("movements accrual")


def test_incurred_dialect_is_admitted():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Incurred", "5"),
        ("Balance at end of period", "105"),
    )
    result = _verdict(rows, caption_stack=("Warranty Reserve",))
    assert result.admitted
    assert result.detail.endswith("movements accrual")


def test_transposed_bookends_are_admitted():
    result = _verdict(_TRANSPOSED, caption_stack=("Warranty Liability Activity",))
    assert result.admitted
    assert "transposed" in result.detail


def test_header_dated_bare_pair_is_admitted():
    rows = (
        ("", "2023", "2024"),
        ("Beginning of period", "1,000", "1,100"),
        ("Accruals for warranties issued", "200", "210"),
        ("End of period", "1,200", "1,310"),
    )
    result = _verdict(rows, caption_stack=("Warranty Liability",))
    assert result.admitted
    assert "header-dated bare pair" in result.detail


def test_dated_pair_is_admitted():
    rows = (
        ("Balance at December 31, 2023", "100"),
        ("Accruals for warranties issued", "10"),
        ("Balance at December 31, 2024", "110"),
    )
    result = _verdict(rows, caption_stack=("Warranty Liability",))
    assert result.admitted
    assert "dated pair" in result.detail


def test_asof_closings_are_admitted():
    rows = (
        ("Balance as of Jan 31, 2024", "100"),
        ("Accruals for warranties issued", "10"),
        ("Balance as of Jun 30, 2024", "110"),
    )
    result = _verdict(rows, caption_stack=("Warranty Liability",))
    assert result.admitted
    assert "as-of closings" in result.detail


def test_subject_not_anchored_is_refused():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Additions", "10"),
        ("Payments", "(5)"),
        ("Balance at end of period", "105"),
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",))
    assert not result.admitted
    assert result.detail == "subject not anchored"


def test_no_bookend_is_refused():
    rows = (
        ("Accruals for warranties issued", "10"),
        ("Settlements", "(5)"),
    )
    result = _verdict(rows, caption_stack=("Warranty Liability",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"


def test_no_movement_is_refused():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Current portion", "40"),
        ("Balance at end of period", "100"),
    )
    result = _verdict(rows, caption_stack=("Warranty Liability",))
    assert not result.admitted
    assert result.detail == "no movement type"


def test_priced_touch_shape_is_admitted_as_priced():
    result = _verdict(_WALK, caption_stack=("Repurchase and Warranty Obligations",))
    assert result.admitted


def test_header_dated_pair_is_admitted():
    rows = (
        ("Activity in the account", "", ""),
        ("", "Year ended December 31, 2024", "Year ended December 31, 2023"),
        ("Beginning of period", "100", "90"),
        ("Accruals for warranties issued", "20", "18"),
        ("End of period", "120", "108"),
    )
    result = _verdict(rows, caption_stack=("Warranty Liability",))
    assert result.admitted
    assert "header-dated pair" in result.detail


def test_header_dated_pair_needs_a_dated_header():
    rows = (
        ("Activity in the account", "", ""),
        ("", "Amount", "Amount"),
        ("Beginning of period", "100", "90"),
        ("Accruals for warranties issued", "20", "18"),
        ("End of period", "120", "108"),
    )
    result = _verdict(rows, caption_stack=("Warranty Liability",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"


def test_asof_header_pair_is_admitted():
    rows = (
        ("", "2024", "2023"),
        ("Balances as of beginning of fiscal year", "100", ""),
        ("Accruals for warranties issued", "20", "18"),
        ("Balances as of January 31", "", "108"),
    )
    result = _verdict(rows, caption_stack=("Warranty Liability",))
    assert result.admitted
    assert "as-of header pair" in result.detail


def test_table_subject_bookend_form_is_admitted():
    rows = (
        (
            "Description",
            "Balance at Beginning of Year",
            "Additions",
            "Balance at End of Year",
        ),
        ("Product warranty", "100", "20", "120"),
        ("Other reserves", "50", "5", "55"),
    )
    result = _verdict(rows, caption_stack=("Valuation and Qualifying Accounts",))
    assert result.admitted
    assert result.detail.endswith("(subject: table bookend form)")


def test_sectioned_table_subject_is_admitted():
    rows = (
        ("Description", "Balance", "Additions", "Deductions"),
        ("December 31, 2024:", "", "", ""),
        ("Product warranty", "100", "20", "15"),
        ("December 31, 2023:", "", "", ""),
        ("Other reserves", "50", "5", "5"),
    )
    result = _verdict(rows, caption_stack=("Valuation and Qualifying Accounts",))
    assert result.admitted
    assert result.detail.endswith("(subject: table bare-pair form)")


def test_fragmented_sectioned_walk_is_admitted():
    rows = (
        ("Description", "", "Beginning"),
        ("Balance", "", "Additions"),
        ("Charges to", "Costs &", "Expenses"),
        ("(3)", "", "Deductions", "", "Ending"),
        ("December 31, 2008:",),
        ("Allowance for doubtful accounts", "100", "10", "90"),
        ("Product warranty", "50", "5", "45"),
        ("December 31, 2007:",),
        ("Allowance for doubtful accounts", "90", "10", "80"),
        ("Product warranty", "45", "5", "40"),
    )
    result = _verdict(rows, caption_stack=("Valuation and Qualifying Accounts",))
    assert result.admitted
    assert result.detail.endswith("(subject: table bare-pair form)")


def test_column_header_pair_subject_is_refused():
    rows = (
        ("December 31,", "", ""),
        ("", "2024", "2023"),
        ("Cash and equivalents", "100", "90"),
        ("Accrued warranty liability", "50", "45"),
        ("Total liabilities", "150", "135"),
    )
    result = _verdict(rows, caption_stack=("Balance Sheet",))
    assert not result.admitted
    assert result.detail == "subject not anchored"


def test_stage_adapter_outcome_scores_the_seat():
    table = _table(_WALK, caption_stack=("Product Warranty Liability",))
    outcomes = [o for o in evaluate_form_tests(table) if o.family == "warranty"]
    assert len(outcomes) == 1
    assert outcomes[0].passed
    assert outcomes[0].points == 3.0


def test_text_and_adapter_paths_agree():
    table = _table(_TRANSPOSED, caption_stack=("Warranty Liability Activity",))
    spec = next(s for s in FORM_TEST_SPECS if s.family == "warranty")
    via_adapter = evaluate_form_test_warranty(table, spec)
    via_text = evaluate_warranty_evidence(WarrantyText.from_table(table), SPEC)
    assert via_adapter.admitted == via_text.admitted
    assert via_adapter.detail == via_text.detail
