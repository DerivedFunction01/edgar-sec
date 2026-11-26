"""Restructuring-evidence gate: registry data, specimen shapes, seat."""

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
    TEST_RESTRUCTURING_EVIDENCE,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.evidence.income_statement.restructuring_evidence import (
    RestructuringText,
    evaluate_form_test_restructuring,
    evaluate_restructuring_evidence,
)
from edgar_sec.engine.tables.extraction.specs.families.restructuring_evidence_specs import (
    RESTRUCTURING_EVIDENCE_SPECS,
    RESTRUCTURING_EVIDENCE_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = RESTRUCTURING_EVIDENCE_SPECS["restructuring"]

_WALK = (
    ("Balance at beginning of period", "$ 10,000"),
    ("Costs incurred and charged to expense", "2,000"),
    ("Cash payments", "(3,000)"),
    ("Balance at end of period", "$ 9,000"),
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
    spec = next(s for s in FORM_TEST_SPECS if s.family == "restructuring")
    return evaluate_form_test_restructuring(
        _table(rows, caption_stack, prose_before), spec
    )


def test_gate_is_declared_as_form_test_data():
    spec = next(s for s in FORM_TEST_SPECS if s.family == "restructuring")
    assert spec.kind == TEST_RESTRUCTURING_EVIDENCE
    assert spec.test_id == "restructuring_rollforward_evidence"
    assert spec.points == 3.0
    assert RESTRUCTURING_EVIDENCE_SPECS_BY_TEST_ID[spec.test_id] is SPEC
    profile = profile_for("restructuring")
    assert profile is not None
    assert TEST_RESTRUCTURING_EVIDENCE in profile.form_tests


def test_canonical_walk_is_admitted():
    result = _verdict(_WALK, caption_stack=("Restructuring Charges",))
    assert result.admitted
    assert "word pair" in result.detail


def test_prose_carried_subject_is_admitted():
    prose = "The company recorded restructuring charges in the year. " + (
        "Further detail follows in the notes to the statements. " * 30
    )
    result = _verdict(_WALK, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert result.admitted
    assert "subject prose" in result.detail


def test_tail_carried_subject_is_admitted():
    prose = ("Detail follows in the notes to the statements. " * 30) + (
        "The balances relate to restructuring activities."
    )
    result = _verdict(_WALK, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert result.admitted


def test_single_movement_type_is_admitted():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Payments", "(40)"),
        ("Balance at end of period", "60"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Reserve",))
    assert result.admitted
    assert result.detail.endswith("movements payment")


def test_costs_row_dialect_is_admitted():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Costs", "40"),
        ("Balance at end of period", "140"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Reserve",))
    assert result.admitted
    assert result.detail.endswith("movements charge")


def test_accruals_noun_dialect_is_admitted():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Accruals", "5"),
        ("Balance at end of period", "105"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Reserve",))
    assert result.admitted
    assert result.detail.endswith("movements charge")


def test_expenditures_dialect_is_admitted():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Expenditures", "5"),
        ("Balance at end of period", "105"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Reserve",))
    assert result.admitted
    assert result.detail.endswith("movements payment")


def test_mid_table_subject_is_refused():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Restructuring charges", "10"),
        ("Payments", "(5)"),
        ("Balance at end of period", "105"),
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",))
    assert not result.admitted
    assert result.detail == "subject not anchored"


def test_loan_context_is_refused_before_claimage():
    result = _verdict(_WALK, caption_stack=("Troubled Debt Restructuring",))
    assert not result.admitted
    assert result.detail == "loan context: scope condition"


def test_prose_touch_on_other_subject_walk_is_admitted_as_priced():
    rows = (
        ("Balance at beginning of period", "100"),
        ("Additions", "10"),
        ("Balance at end of period", "110"),
    )
    prose = "During the year the company undertook a restructuring program."
    result = _verdict(rows, caption_stack=("Goodwill",), prose_before=prose)
    assert result.admitted


def test_dated_header_without_movement_term_is_refused():
    rows = (
        ("Activity in the reserve account", "", ""),
        ("", "December 31, 2024", "December 31, 2023"),
        ("Charges", "10", "-"),
        ("Payments", "(4)", "-"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Reserve",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"


def test_dated_header_bookend_is_admitted():
    rows = (
        (
            "",
            "December 31, 2021",
            "",
            "Charges",
            "",
            "Cash Payments",
            "",
            "December 31, 2022",
        ),
        ("Employee severance", "$ —", "$ 3,444", "$ (3,050)", "$ 394"),
        ("Total", "$ —", "$ 3,444", "$ (3,050)", "$ 394"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Reserve",))
    assert result.admitted
    assert "dated header" in result.detail


def test_remaining_closing_bookend_is_admitted():
    rows = (
        (
            "",
            "Beginning Liability",
            "",
            "Expenses, Net",
            "",
            "Amounts Paid",
            "",
            "Remaining Liability",
        ),
        ("Employee termination benefits", "$ 5,991", "$ 9,383", "$ (8,628)"),
        ("Facility and other costs", "71", "77", "(108)"),
        ("Total", "$ 6,062", "$ 9,460", "$ (8,736)"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Liability",))
    assert result.admitted
    assert "remaining closing" in result.detail


def test_bare_closing_row_bookend_is_admitted():
    rows = (
        ("Costs", "", "Facilities", "", "Total"),
        ("Charges", "$ 21,633", "$ 1,762", "$ 23,472"),
        ("Payments", "(9,465)", "(148)", "(9,627)"),
        ("April 4, 2009", "$ 12,321", "$ 1,694", "$ 14,078"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert result.admitted
    assert "bare closing" in result.detail


def test_dated_row_pair_alone_is_refused():
    rows = (
        ("", "Canada", "", "Europe", "", "Total", ""),
        ("Total at December 31, 2015", "$ 2.3", "$ 5.6", "$ 9.2"),
        ("Payments made", "(0.1)", "(0.7)", "(2.1)"),
        ("Changes in estimates", "—", "(2.2)", "(2.2)"),
        ("Total at September 30, 2016", "$ 2.2", "$ 2.3", "$ 4.5"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"


def test_dated_pair_bookends_are_admitted():
    rows = (
        ("Balance at December 31, 2023", "100"),
        ("Charges incurred", "10"),
        ("Balance at December 31, 2024", "110"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Reserve",))
    assert result.admitted
    assert "dated pair" in result.detail


def test_anchor_pair_bookends_are_admitted():
    rows = (
        ("Accrued liability, December 31, 2023", "100"),
        ("Charges", "10"),
        ("Accrued liability, December 31, 2024", "110"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Reserve",))
    assert result.admitted
    assert "anchor pair" in result.detail


def test_form_test_stage_scores_the_seat_points():
    table = _table(_WALK, caption_stack=("Restructuring Charges",))
    outcomes = [
        o
        for o in evaluate_form_tests(table)
        if o.test_id == "restructuring_rollforward_evidence"
    ]
    assert len(outcomes) == 1
    assert outcomes[0].passed
    assert outcomes[0].points == 3.0


def test_text_level_evaluator_matches_the_adapter():
    text = RestructuringText(
        caption="Restructuring Charges",
        prose="",
        lines=tuple(" | ".join(row) for row in _WALK),
    )
    assert evaluate_restructuring_evidence(text, SPEC).admitted


def test_exit_cost_liability_walk_is_admitted():
    # Specimen 0001413329-23-000117:49: the walk's subject is
    # "exit cost liabilities", never "restructuring".
    rows = (
        ("Liability balance, January 1, 2023", "100"),
        ("Charges, net", "20"),
        ("Cash spent", "(15)"),
        ("Liability balance, March 31, 2023", "105"),
    )
    result = _verdict(rows, caption_stack=("Movement in Exit Cost Liabilities",))
    assert result.admitted


def test_employee_separation_walk_is_admitted():
    # Specimen 0001047127-12-000009:32: the walk is carried as
    # "employee separation costs" with accrual bookends.
    rows = (
        ("Accrual at December 31, 2011", "50"),
        ("Charges", "10"),
        ("Cash Payments", "(8)"),
        ("Accrual at June 30, 2012", "52"),
    )
    result = _verdict(rows, caption_stack=("Employee Separation Costs",))
    assert result.admitted


def test_prose_subject_across_a_numbered_heading_is_refused():
    # The mention sits in the prior note's narrative; a numbered
    # heading boundary separates it from this table.
    prose = (
        "The Club Monaco restructuring plan recorded restructuring charges "
        "against the remaining liability for the year. "
        "\n13. Income Taxes\n"
        + "The provision for income taxes reflects domestic and foreign "
        "pretax income for the periods presented. " * 12
    )
    result = _verdict(_WALK, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert not result.admitted
    assert result.detail == "subject not anchored"


def test_prose_subject_after_a_numbered_heading_is_admitted():
    prose = (
        "The components of income before taxes follow. "
        "\n13. Income Taxes\n"
        + "The provision for income taxes reflects domestic and foreign "
        "pretax income for the periods presented. "
        * 6
        + "The company also recorded restructuring charges under the plan. "
        + "Further detail follows in the notes to the financial statements. " * 12
    )
    result = _verdict(_WALK, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert result.admitted
    assert "subject prose" in result.detail


def test_prose_subject_across_a_caps_title_is_refused():
    # The mention is incidental prose; an all-caps statement
    # title boundary separates it from this table.
    prose = (
        "In connection with a restructuring of our international holdings, "
        "the company identified distributable foreign earnings. "
        "\nCONDENSED CONSOLIDATED STATEMENTS OF EQUITY\n"
        + "Further detail follows in the notes to the financial statements. "
        * 12
    )
    result = _verdict(_WALK, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert not result.admitted
    assert result.detail == "subject not anchored"


def test_last_prose_mention_after_the_boundary_governs():
    prose = (
        "The restructuring narrative for the prior year follows. "
        "\n13. Income Taxes\n"
        + "The provision for income taxes reflects domestic and foreign "
        "pretax income for the periods presented. "
        * 6
        + "The current year restructuring charges are described below. "
        + "Further detail follows in the notes to the financial statements. " * 12
    )
    result = _verdict(_WALK, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert result.admitted
    assert "subject prose" in result.detail


def test_caption_anchor_ignores_the_prose_boundary():
    prose = (
        "The Club Monaco restructuring plan recorded restructuring charges "
        "against the remaining liability for the year. "
        "\n13. Income Taxes\n"
        + "The provision for income taxes reflects domestic and foreign "
        "pretax income for the periods presented. " * 12
    )
    result = _verdict(
        _WALK, caption_stack=("Restructuring Charges",), prose_before=prose
    )
    assert result.admitted
    assert "subject lead" in result.detail


def test_tail_subject_across_a_heading_is_refused():
    # The surviving Round 4 false's shape: the only subject
    # mention sits inside the prose tail, before a heading.
    filler = (
        "The provision for income taxes reflects domestic and foreign "
        "pretax income for the periods presented. "
    )
    tail = (
        "The balances relate to restructuring activities. "
        "\n13. Income Taxes\n" + filler * 3
    )
    prose = "Introductory detail without the subject term.\n" + filler * 8 + tail
    result = _verdict(_WALK, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert not result.admitted
    assert result.detail == "subject not anchored"


def test_tail_subject_after_a_heading_is_admitted():
    filler = (
        "The provision for income taxes reflects domestic and foreign "
        "pretax income for the periods presented. "
    )
    tail = (
        "\n13. Income Taxes\n"
        + filler * 3
        + ("The balances relate to restructuring activities.")
    )
    prose = "Introductory detail without the subject term.\n" + filler * 8 + tail
    result = _verdict(_WALK, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert result.admitted


def test_charge_incidence_table_stays_outside_the_walk_gate():
    # The incidence sub-kind carries no accrual walk; the term
    # set does not seat it (a determination split, not built).
    rows = (
        ("Segment A", "10"),
        ("Segment B", "5"),
        ("Total charges", "15"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges by Segment",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"


def test_charges_stub_form_is_admitted():
    # Cost-type row stubs with values: the seated charges anatomy.
    rows = (
        ("Severance costs", "100", "200"),
        ("Facility exit costs", "50", "60"),
        ("Employee termination benefits", "10", "20"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert result.admitted
    assert "charges signature: cost stubs" in result.detail


def test_charges_period_form_is_admitted():
    # Charges-by-period matrix: the cost vocabulary sits in the
    # column headers, the row labels are fiscal periods.
    rows = (
        ("", "Cost of Sales", "Restructuring Charges", "Total"),
        ("Fiscal 2019", "22", "133", "241"),
        ("Fiscal 2020", "10", "34", "83"),
        ("Fiscal 2021", "8", "(15)", "7"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert result.admitted
    assert "charges signature: period form" in result.detail


def test_charges_segment_form_is_admitted():
    # Charges-by-segment table: the charges vocabulary sits in
    # the total row, the row labels are business lines.
    rows = (
        ("Mobility", "$", "67"),
        ("Delivery", "32", ""),
        ("Freight", "7", ""),
        ("Total restructuring and related charges", "281", ""),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert result.admitted
    assert "charges signature: segment form" in result.detail


def test_charges_with_cash_flow_anatomy_stays_out():
    # The cash-flow anatomy veto binds every charges form.
    rows = (
        ("Cash flows from operating activities", "", ""),
        ("Severance costs", "100", "200"),
        ("Facility exit costs", "50", "60"),
        ("Employee termination benefits", "10", "20"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"
