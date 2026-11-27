"""Restructuring summary guard: the Form B admission discipline."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.engine.tables.extraction.evidence.income_statement.restructuring_evidence import (
    RestructuringText,
    evaluate_form_test_restructuring,
    evaluate_restructuring_evidence,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.specs.families.restructuring_evidence_specs import (
    RESTRUCTURING_EVIDENCE_SPECS,
)

SPEC = RESTRUCTURING_EVIDENCE_SPECS["restructuring"]


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


def test_summary_form_is_admitted():
    # The Form B summary fragment: charge-type summary rows and
    # a Total row, no balance line, at least 3 data rows.
    rows = (
        ("Severance and related costs", "120"),
        ("Facility exit costs", "45"),
        ("Other exit costs", "12"),
        ("Total", "177"),
    )
    prose = "The company recorded restructuring charges in the year."
    result = _verdict(
        rows, caption_stack=("Restructuring Charges",), prose_before=prose
    )
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
        prose="The company recorded restructuring charges during the year.",
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
        prose="The company recorded restructuring charges during the year.",
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


def test_summary_guard_refuses_lending_sense():
    # N1: a troubled-debt-restructuring table — "restructuring"
    # in the lending sense — is refused however it is captioned.
    rows = (
        ("", "Initial Restructuring", "Multiple Restructurings"),
        ("Commercial and industrial", "10", "2"),
        ("Consumer installment", "5", "1"),
        ("Agricultural", "3", "0"),
        ("Total", "18", "3"),
    )
    prose = (
        "The company enters into troubled debt restructurings "
        "with certain borrowers experiencing financial difficulty."
    )
    result = _verdict(
        rows,
        caption_stack=("Restructurings that occurred during the year",),
        prose_before=prose,
    )
    assert not result.admitted
    assert result.detail == "summary form refused: lending sense"


def test_summary_guard_refuses_derivative_anatomy():
    # N2: derivative rows are competing anatomy under the
    # extended veto.
    rows = (
        ("Derivative assets", "10"),
        ("Derivative liabilities", "5"),
        ("Severance costs", "3"),
        ("Total", "18"),
    )
    prose = "The company recorded restructuring charges in the year."
    result = _verdict(
        rows, caption_stack=("Restructuring Charges",), prose_before=prose
    )
    assert not result.admitted
    assert result.detail == "summary form refused: competing anatomy"


def test_summary_guard_refuses_a_note_family_title():
    # N4: a summary under a note naming another family is
    # refused — the note's subject governs.
    text = RestructuringText(
        caption="Restructuring Charges",
        note_title="Segment Information",
        prose="The company recorded restructuring charges during the year.",
        lines=(
            "Severance and related costs | 120",
            "Facility exit costs | 45",
            "Other exit costs | 12",
            "Total | 177",
        ),
    )
    result = evaluate_restructuring_evidence(text, SPEC)
    assert not result.admitted
    assert result.detail == "summary form refused: note names another family"


def test_summary_guard_refuses_subject_free_prose():
    # N3: a lead-anchored summary whose introducing prose never
    # names the subject is refused — the anchor was satisfied
    # by context outside the geometry's own account.
    rows = (
        ("Severance and related costs", "120"),
        ("Facility exit costs", "45"),
        ("Other exit costs", "12"),
        ("Total", "177"),
    )
    prose = (
        "The following table presents the accrued liability "
        "by category for the periods presented."
    )
    result = _verdict(
        rows, caption_stack=("Restructuring Charges",), prose_before=prose
    )
    assert not result.admitted
    assert result.detail == "summary form refused: prose subject absent"
