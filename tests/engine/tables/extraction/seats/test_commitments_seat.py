"""Commitments seat: geometry-text claims, T5 specimen shapes."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.scoring.classify import classify_table
from edgar_sec.engine.tables.extraction.seats.commitments_seat import (
    FORM_CREDIT_CLUSTER,
    FORM_GUARANTEE_SCHEDULE,
    FORM_PAYMENTS_DUE,
    POINTS_CLUSTER,
    POINTS_PAYMENTS_DUE,
    evaluate_commitments_seat,
    seat_region,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.text.context import (
    NoteRef,
    SectionRef,
    TableContext,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROFILES_BY_FAMILY,
    SEAT_GEOMETRY_TEXT,
)
from edgar_sec.engine.tables.extraction.cascade.residue_families import corroborates
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    RowKind,
    TypedTable,
    structure_table,
)

_MDA = "Management's Discussion and Analysis of Financial Condition"


def _table(
    rows: tuple[tuple[str, ...], ...],
    *,
    note_title: str | None = None,
    section_title: str | None = None,
    seat: str | None = None,
) -> TypedTable:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows, column_alignments=(), column_widths=(), header_row_count=0
            ),
            confidence=1.0,
        ),
    )
    context = TableContext(
        geometry=geometry,
        note=NoteRef(9, None, note_title) if note_title is not None else None,
        section=SectionRef(None, section_title) if section_title else None,
        seat=seat,
    )
    return structure_table(context)


def test_a_capitalized_total_row_is_typed_total_in_a_seat_table() -> None:
    # The seat consumes structure_table output, whose row kinds come from
    # typed_rows' homed TOTAL_ROW_RE — case-insensitive by design.
    table = _table(
        (
            ("Purchase obligations", "1,000", "400"),
            ("Total contractual obligations", "1,500", "600"),
        ),
        section_title=_MDA,
        seat="mda",
    )
    assert any(
        row.kind is RowKind.TOTAL and "total contractual" in row.label.lower()
        for row in table.rows
    )


def test_profile_seat_is_the_relocated_geometry_text_seat() -> None:
    profile = PROFILES_BY_FAMILY["commitments_contingencies"]
    assert profile.vocabulary_seat == SEAT_GEOMETRY_TEXT
    assert profile.gate_bindings == ("commitments_seat",)


def test_payments_due_in_mda_claims_on_the_purchase_row() -> None:
    table = _table(
        (
            (
                "",
                "Total",
                "Less than 1 year",
                "1 to 3 years",
                "3 to 5 years",
                "More than 5 years",
            ),
            ("Purchase obligations", "1,000", "400", "300", "200", "100"),
            ("Operating lease obligations", "500", "200", "150", "100", "50"),
            ("Total contractual obligations", "1,500", "600", "450", "300", "150"),
        ),
        section_title=_MDA,
        seat="mda",
    )
    verdict = evaluate_commitments_seat(table)
    assert verdict.passed and verdict.form == FORM_PAYMENTS_DUE
    assert verdict.points == POINTS_PAYMENTS_DUE and verdict.region == "mda"
    assert classify_table(table).family == "commitments_contingencies"


def test_payments_due_in_a_note_region_claims_without_the_old_title() -> None:
    table = _table(
        (
            (
                "",
                "Total",
                "Less than 1 year",
                "1 to 3 years",
                "3 to 5 years",
                "More than 5 years",
            ),
            ("Purchase commitments", "800", "300", "250", "150", "100"),
            ("Operating leases", "200", "80", "60", "40", "20"),
        ),
        note_title="Commitments",
    )
    verdict = evaluate_commitments_seat(table)
    assert verdict.passed and verdict.form == FORM_PAYMENTS_DUE
    assert verdict.region == "note"


def test_fhlb_off_balance_sheet_cluster_claims_by_expiry() -> None:
    table = _table(
        (
            ("Off-Balance Sheet Commitments",),
            (
                "",
                "Total",
                "Less than 1 year",
                "1 to 3 years",
                "3 to 5 years",
                "More than 5 years",
            ),
            ("Standby letters of credit", "900", "300", "250", "200", "150"),
            ("Standby bond purchase agreements", "400", "100", "100", "100", "100"),
            ("Commitments for unused lines of credit", "700", "700", "", "", ""),
        ),
        note_title="Financial Instruments",
    )
    verdict = evaluate_commitments_seat(table)
    assert verdict.passed and verdict.form == FORM_CREDIT_CLUSTER
    assert verdict.points == POINTS_CLUSTER


def test_bank_commitments_cluster_claims_on_single_amounts() -> None:
    table = _table(
        (
            ("Commitments to extend credit", "100"),
            ("Unused lines of credit", "50"),
            ("Standby letters of credit", "25"),
            ("Total commitments", "175"),
        ),
        note_title="Commitments",
    )
    verdict = evaluate_commitments_seat(table)
    assert verdict.passed and verdict.form == FORM_CREDIT_CLUSTER
    assert classify_table(table).family == "commitments_contingencies"


def test_guarantee_schedule_claims_with_a_credit_companion() -> None:
    table = _table(
        (
            ("Surety bonds and bank guarantees", "1,464"),
            ("Letters of credit outstanding", "309"),
            ("Total", "1,773"),
        ),
        note_title="Commitments and Contingencies",
    )
    verdict = evaluate_commitments_seat(table)
    assert verdict.passed and verdict.form == FORM_GUARANTEE_SCHEDULE


def test_commercial_commitments_by_year_claim_as_guarantee_form() -> None:
    table = _table(
        (
            ("Commercial Commitments",),
            ("", "2023", "2024", "2025", "2026", "Thereafter", "Total"),
            ("Standby letters of credit", "10", "20", "30", "40", "50", "150"),
            ("Bank guarantees", "5", "5", "5", "5", "5", "25"),
        ),
        note_title="Commitments and Contingencies",
    )
    verdict = evaluate_commitments_seat(table)
    assert verdict.passed and verdict.form == FORM_GUARANTEE_SCHEDULE


def test_payments_due_without_a_purchase_row_is_not_a_member() -> None:
    table = _table(
        (
            (
                "",
                "Total",
                "Less than 1 year",
                "1 to 3 years",
                "3 to 5 years",
                "More than 5 years",
            ),
            ("Long-term debt", "2,000", "500", "600", "500", "400"),
            ("Operating leases", "500", "200", "150", "100", "50"),
            ("Finance leases", "100", "40", "30", "20", "10"),
        ),
        section_title=_MDA,
        seat="mda",
    )
    assert not evaluate_commitments_seat(table).passed
    assert classify_table(table).family != "commitments_contingencies"


def test_borrowings_with_a_lone_letter_of_credit_line_refuse() -> None:
    table = _table(
        (
            ("Revolving credit facility borrowings", "200"),
            ("Letters of credit outstanding", "10"),
            ("Total borrowings", "210"),
        ),
        note_title="Long-Term Debt",
    )
    assert not evaluate_commitments_seat(table).passed
    assert classify_table(table).family != "commitments_contingencies"


def test_fee_and_rate_tables_refuse() -> None:
    table = _table(
        (
            ("Commitment fee rate", "0.25"),
            ("Applicable margin", "1.75"),
            ("Letter of credit fee", "1.50"),
        ),
        note_title="Credit Agreement",
    )
    assert not evaluate_commitments_seat(table).passed


def test_debt_year_ladder_is_not_a_commitments_claim() -> None:
    table = _table(
        (
            ("", "2026", "2027", "2028", "2029", "2030", "Thereafter", "Total"),
            ("Long-term debt", "100", "200", "300", "400", "500", "600", "2,100"),
            ("Notes payable", "10", "20", "30", "40", "50", "60", "210"),
        ),
        note_title="Long-Term Debt",
    )
    assert not evaluate_commitments_seat(table).passed
    assert classify_table(table).family != "commitments_contingencies"


def test_the_form_outside_mda_and_note_regions_refuses() -> None:
    table = _table(
        (
            (
                "",
                "Total",
                "Less than 1 year",
                "1 to 3 years",
                "3 to 5 years",
                "More than 5 years",
            ),
            ("Purchase obligations", "1,000", "400", "300", "200", "100"),
        ),
        seat="item_1",
    )
    assert seat_region(table) is None
    assert not evaluate_commitments_seat(table).passed


def test_uncorroborated_sibling_grid_still_earns_no_claim() -> None:
    table = _table(
        (
            ("Cash and cash equivalents", "100"),
            ("Accounts receivable", "50"),
            ("Inventories", "25"),
        ),
        note_title="Commitments and Contingencies",
    )
    assert not evaluate_commitments_seat(table).passed
    assert classify_table(table).family != "commitments_contingencies"


def test_note_corroboration_counts_the_credit_cluster_terms() -> None:
    grid = GeometryText(
        stubs=("commitments to extend credit", "unused lines of credit")
    )
    assert corroborates("commitments_contingencies", grid)
