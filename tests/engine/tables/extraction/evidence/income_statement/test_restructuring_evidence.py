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


def test_dated_row_pair_alone_is_no_bookend_but_seats_as_summary():
    # A dated row pair alone files no bookend pair — that
    # determination stands — but the fragment's shape (a Total
    # row in the header and the Total-at rows, no balance line,
    # 4 data rows) is the programme-adopted summary form, so it
    # seats as a summary claim, not a walk.
    rows = (
        ("", "Canada", "", "Europe", "", "Total", ""),
        ("Total at December 31, 2015", "$ 2.3", "$ 5.6", "$ 9.2"),
        ("Payments made", "(0.1)", "(0.7)", "(2.1)"),
        ("Changes in estimates", "\u2014", "(2.2)", "(2.2)"),
        ("Total at September 30, 2016", "$ 2.2", "$ 2.3", "$ 4.5"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert result.admitted
    assert result.detail.startswith("restructuring summary: subject lead")


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


def test_charge_incidence_table_seats_under_the_summary_form():
    # The incidence sub-kind carries no accrual walk and stays
    # outside the walk gate; under the programme-adopted summary
    # form (Form B) its shape — a Total row, no balance line,
    # 3 data rows — seats as a summary claim, not a walk.
    rows = (
        ("Segment A", "10"),
        ("Segment B", "5"),
        ("Total charges", "15"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges by Segment",))
    assert result.admitted
    assert result.detail.startswith("restructuring summary: subject lead")


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


def test_header_form_is_admitted():
    # Walk table whose charge-type vocabulary sits in the column
    # headers, over a total-charge row and a balance-at closing row.
    rows = (
        ("Employee severance benefits", "Facility closure costs", "Other", "Total"),
        ("Total charge", "$ 313", "$ 25", "$ 4", "$ 342"),
        ("Less: Amounts paid", "287", "—", "—", "287"),
        ("Non-cash charges", "—", "—", "4", "4"),
        ("Balance at December 31, 2002", "$ 26", "25", "$ —", "$ 51"),
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",))
    assert result.admitted
    assert "subject header" in result.detail
    assert "bookends closing balance" in result.detail


def test_header_vocabulary_without_balance_at_stays_out():
    # Two header charge types alone do not anchor: the
    # balance-at closing row is the header form's second leg.
    rows = (
        ("Employee severance benefits", "Facility closure costs", "Other", "Total"),
        ("Total charge", "$ 313", "$ 25", "$ 4", "$ 342"),
        ("Less: Amounts paid", "287", "—", "—", "287"),
        ("Non-cash charges", "—", "—", "4", "4"),
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",))
    assert not result.admitted
    assert result.detail == "subject not anchored"


def test_single_header_term_with_balance_at_stays_out():
    # One header charge type is below the header form's count.
    rows = (
        ("Employee severance benefits", "Other", "Total"),
        ("Total charge", "$ 313", "$ 4", "$ 342"),
        ("Less: Amounts paid", "287", "—", "287"),
        ("Balance at December 31, 2002", "$ 26", "$ —", "$ 51"),
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",))
    assert not result.admitted
    assert result.detail == "subject not anchored"


def test_header_form_without_charge_line_has_no_bookend():
    # The closing-balance form needs a charge line as well as
    # the balance-at row; neither leg alone is a bookend pair.
    rows = (
        ("Severance benefits", "Facility closure costs", "Total"),
        ("Amounts paid", "10", "20", "30"),
        ("Balance at March 31, 2006", "1", "2", "3"),
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"


def test_summary_form_is_admitted():
    # The Form B summary fragment: charge-type summary rows and
    # a Total row, no balance line, at least 3 data rows.
    rows = (
        ("Severance and related costs", "120"),
        ("Facility exit costs", "45"),
        ("Other exit costs", "12"),
        ("Total", "177"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert result.admitted
    assert result.detail.startswith("restructuring summary: subject lead")
    assert "summary form, data rows 4" in result.detail


def test_summary_form_with_a_balance_line_stays_out():
    # A balance line anywhere takes the fragment out of the
    # summary shape (and no bookend pair is filed here).
    rows = (
        ("Severance and related costs", "120"),
        ("Facility exit costs", "45"),
        ("Balance carried forward", "5"),
        ("Total", "170"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"


def test_summary_form_below_three_data_rows_stays_out():
    rows = (
        ("Severance and related costs", "120"),
        ("Facility exit costs", "45"),
        ("Total restructuring costs", ""),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"


def test_summary_form_without_a_total_row_stays_out():
    rows = (
        ("Severance and related costs", "120"),
        ("Facility exit costs", "45"),
        ("Other exit costs", "12"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert not result.admitted
    assert result.detail == "no bookend pair in any filed form"


def test_summary_guard_refuses_a_prose_anchor():
    # A summary fragment whose subject arrives only through the
    # prose arm is refused by the guard: the priced V3 form
    # requires a lead anchor (caption, note, tail, first line).
    rows = (
        ("Other charges", "120"),
        ("Administrative expenses", "45"),
        ("Selling expenses", "12"),
        ("Total", "177"),
    )
    prose = "The company recorded restructuring charges in the year. " + (
        "Further detail follows in the notes to the statements. " * 30
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert not result.admitted
    assert result.detail == "summary form refused: prose anchor"


def test_summary_guard_refuses_competing_anatomy():
    # A lead-anchored fragment whose own rows are a revenue
    # statement's anatomy is refused, however it is captioned.
    rows = (
        ("North America", "100"),
        ("Europe", "80"),
        ("Other regions", "20"),
        ("Total revenue", "200"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Charges",))
    assert not result.admitted
    assert result.detail == "summary form refused: competing anatomy"


def test_summary_guard_refuses_missing_charge_vocabulary():
    # The payment-schedule shape: lead-anchored through a subject
    # term outside the charge vocabulary, with no charge word in
    # its rows or its head — refused (the priced :14 kill).
    rows = (
        ("Year ending December 31, 2006", "5.9"),
        ("Year ending December 31, 2007", "4.3"),
        ("Year ending December 31, 2008", "3.4"),
        ("Total", "13.6"),
    )
    result = _verdict(rows, caption_stack=("Employee Separation Program",))
    assert not result.admitted
    assert result.detail == "summary form refused: no charge vocabulary"


def test_summary_guard_admits_a_note_carried_segment_summary():
    # The adopted :217 shape: segment-name rows and a Total,
    # the subject and the charge vocabulary carried by the note
    # title — admitted as a summary claim.
    text = RestructuringText(
        caption="",
        note_title="Restructuring",
        prose="",
        lines=(
            "Eastern | $ 4",
            "Midwest | 3",
            "South | 5",
            "West | 2",
            "Corporate | 1",
            "Eliminations | 1",
            "Total | $ 19",
        ),
    )
    result = evaluate_restructuring_evidence(text, SPEC)
    assert result.admitted
    assert result.detail.startswith("restructuring summary: subject lead")


def test_summary_guard_admits_a_parenthesized_marker():
    # R-A: an anatomy marker inside parentheses (a column
    # qualifier) does not veto — the priced :78 recovery shape.
    text = RestructuringText(
        lines=(
            "Program | Sales Returns (included in Net Sales) | Charges | Amount",
            "Plan A | 10 | 2 | 12",
            "Plan B | 8 | 1 | 9",
            "Total | 18 | 3 | 21",
        ),
        caption="Charges Associated with Restructuring and Other Activities",
        note_title="",
        prose="",
    )
    result = evaluate_restructuring_evidence(text, SPEC)
    assert result.admitted
    assert result.detail.startswith("restructuring summary: subject lead")


def test_summary_guard_admits_a_two_charge_type_prose_form():
    # R-B: a prose-anchored summary whose own rows carry at
    # least two distinct charge types is admitted — the priced
    # :23 recovery shape.
    rows = (
        ("Severance and related costs", "120"),
        ("Facility exit costs", "45"),
        ("Asset impairments", "12"),
        ("Total", "177"),
    )
    prose = "The company recorded restructuring charges in the year. " + (
        "Further detail follows in the notes to the statements. " * 30
    )
    result = _verdict(rows, caption_stack=("Accrued Liabilities",), prose_before=prose)
    assert result.admitted
    assert result.detail.startswith("restructuring summary: subject prose")


def test_summary_guard_refuses_an_extended_anatomy_total():
    # C3: a commitments total is competing anatomy under the
    # extended veto — the priced :26 kill shape.
    rows = (
        ("Operating leases", "128.8", "14.7"),
        ("Restructurings", "15.8", "6.0"),
        ("Purchase obligations", "2.6", "0.7"),
        ("Total commitments", "153.4", "24.4"),
    )
    result = _verdict(rows, caption_stack=("Restructuring Commitments",))
    assert not result.admitted
    assert result.detail == "summary form refused: competing anatomy"
