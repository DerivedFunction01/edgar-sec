"""Primary hard gates: detector pins, clusters, gate act."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.filing_competition import compete_filing
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.seats.primary_gate import (
    missing_sections,
    section_presence,
    statement_clusters,
)
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    SignatureTerm,
)

_TERMS = (
    SignatureTerm("balance_sheet", "caption", "balance sheet", 2.5, 40, 1),
    SignatureTerm("balance_sheet", "leadin", "balance sheet", 2.5, 35, 1),
    SignatureTerm("balance_sheet", "stub", "total assets", 2.5, 30, 0),
    SignatureTerm("equity_statement", "caption", "changes in equity", 2.5, 40, 1),
    SignatureTerm("equity_statement", "leadin", "statement of changes", 2.5, 38, 1),
    SignatureTerm("equity_statement", "notehead", "changes in equity", 2.5, 40, 2),
    SignatureTerm("equity_statement", "stub", "shares issued", 2.0, 30, 5),
    SignatureTerm("lease_maturity", "caption", "operating lease", 2.5, 40, 2),
    SignatureTerm("lease_maturity", "leadin", "lease liabilities", 2.5, 35, 1),
    SignatureTerm("lease_maturity", "stub", "undiscounted lease payments", 2.5, 30, 0),
)


def test_balance_sheet_detector_complete_and_missing_equity() -> None:
    complete = (
        "Current assets",
        "Total current liabilities",
        "Total stockholders' equity",
    )
    assert missing_sections(complete, "balance_sheet") == []
    incomplete = ("Current assets", "Total current liabilities")
    assert missing_sections(incomplete, "balance_sheet") == ["equity"]


def test_balance_sheet_detector_noncorporate_equity_captions() -> None:
    partnership = (
        "Total assets",
        "Total liabilities",
        "Total partnership capital",
    )
    assert missing_sections(partnership, "balance_sheet") == []
    insurer = (
        "Total assets",
        "Total liabilities",
        "Total policyholders' surplus",
    )
    assert missing_sections(insurer, "balance_sheet") == []
    combined = (
        "Total assets",
        "Total liabilities and partnership capital",
    )
    assert missing_sections(combined, "balance_sheet") == []


def test_average_balance_form_has_no_summary_equity() -> None:
    # The re-determination's named ambiguous form: equity exists
    # only inside combined temporary/permanent captions.
    stubs = (
        "Total assets",
        "Total liabilities",
        "Liabilities, Temporary Equity and Permanent Equity",
        "Total temporary equity",
        "Total permanent equity",
    )
    assert missing_sections(stubs, "balance_sheet") == ["equity"]


def test_cash_flow_detector_headers_totals_and_reconciliation() -> None:
    headers = (
        "Cash flows from operating activities",
        "Cash flows from investing activities",
        "Cash flows from financing activities",
        "Cash and cash equivalents, beginning of period",
    )
    assert missing_sections(headers, "cash_flow") == []
    totals = (
        "Net cash provided by operating activities",
        "Net cash used in investing activities",
        "Net cash provided by financing activities",
        "Net increase in cash",
    )
    assert missing_sections(totals, "cash_flow") == []
    assert missing_sections(headers[:3], "cash_flow") == ["cash_reconciliation"]


def test_income_statement_detector_and_tax_is_measure_only() -> None:
    stubs = (
        "Total revenues",
        "Total operating expenses",
        "Other income, net",
        "Net income",
    )
    assert missing_sections(stubs, "income_statement") == []
    presence = section_presence(stubs, "income_statement")
    assert presence["income_tax"] is False
    assert "income_tax" not in missing_sections(stubs, "income_statement")


def test_equity_detector_lexical_and_dated_balance_rows() -> None:
    lexical = (
        "Balance at beginning of year",
        "Net income",
        "Dividends declared",
        "Balance at end of year",
    )
    assert missing_sections(lexical, "equity_statement") == []
    dated = (
        "Balance, January 1, 2023",
        "Shares issued",
        "Balance, December 31, 2023",
    )
    assert missing_sections(dated, "equity_statement") == []
    one_dated = ("Balance, January 1, 2023", "Shares issued")
    assert missing_sections(one_dated, "equity_statement") == ["ending_balances"]


def test_equity_detector_single_dated_balance_row_closes_bookend() -> None:
    # Priced (GEQ, equity_statement residual census on e486ceff):
    # a lone closing balance stub in the "Balance(s) at/as of
    # <date>" or "Balance(s) <month> <day>, <year>" form is the
    # statement's ending balance — the opening row sits in the
    # header band of the single-table quarterly form.
    as_of = ("Net income", "Dividends on common stock", "Balance as of June 30, 2015")
    assert missing_sections(as_of, "equity_statement") == []
    at = ("Stock-based compensation", "Balances at September 30, 2020")
    assert missing_sections(at, "equity_statement") == []
    month_first = ("Share-based compensation", "Balance August 2, 2020")
    assert missing_sections(month_first, "equity_statement") == []


def test_comprehensive_detector_and_parenthesized_total() -> None:
    stubs = ("Net income", "Other comprehensive income", "Total comprehensive income")
    assert missing_sections(stubs, "comprehensive_income") == []
    # The attribution-caption shape is gate-complete: the
    # parenthesized total form fires (a priced survivor shape).
    attributed = (
        "Net income",
        "Other comprehensive income",
        "Total comprehensive income (loss) attributable to Acme Corp",
    )
    assert missing_sections(attributed, "comprehensive_income") == []


def test_comprehensive_known_miss_gain_loss_parenthesized() -> None:
    # Known miss of record (specimen 0001558370-18-005106:18):
    # the parenthesized gain (loss) form fires no OCI pattern.
    stubs = (
        "Net income",
        "Net unrealized gain (loss) on available-for-sale investments",
        "Total comprehensive income",
    )
    presence = section_presence(stubs, "comprehensive_income")
    assert presence["oci_components"] is False
    assert missing_sections(stubs, "comprehensive_income") == ["oci_components"]


def test_combined_detector_is_income_statement_plus_total_ci() -> None:
    stubs = (
        "Total revenues",
        "Total operating expenses",
        "Other income, net",
        "Net income",
        "Total comprehensive income",
    )
    assert missing_sections(stubs, "combined_operations_ci") == []
    assert missing_sections(stubs[:4], "combined_operations_ci") == [
        "total_comprehensive_income"
    ]


def test_clusters_join_on_home_and_head_caption() -> None:
    geometries = [
        GeometryText(caption="Balance Sheet", note_title="Notes"),
        GeometryText(note_title="Notes"),
        GeometryText(caption="Balance Sheet", note_title="Notes"),
        GeometryText(caption="Cash Flow", note_title="Notes"),
        GeometryText(note_title="Other"),
    ]
    clusters = statement_clusters(geometries)
    assert clusters[0] == (0, 1, 2)
    assert clusters[1] == (0, 1, 2)
    assert clusters[2] == (0, 1, 2)
    assert clusters[3] == (3,)
    assert clusters[4] == (4,)


def test_cluster_captioned_geometry_after_uncaptioned_starts_run() -> None:
    geometries = [
        GeometryText(note_title="Notes"),
        GeometryText(caption="Balance Sheet", note_title="Notes"),
    ]
    clusters = statement_clusters(geometries)
    assert clusters[0] == (0,)
    assert clusters[1] == (1,)


def test_gate_refuses_incomplete_primary_claim() -> None:
    geometry = GeometryText(
        caption="Consolidated Balance Sheets",
        leadin="Balance sheet as of December 31, 2023.",
        stubs=("Total assets", "Total liabilities"),
    )
    (result,) = compete_filing([geometry], terms=_TERMS, edges=())
    assert result.claims == ()
    assert result.contested == ()
    assert result.groups == ()
    trail = result.scores["balance_sheet"].evidence
    gate = [entry for entry in trail if entry.channel == "gate"]
    assert len(gate) == 1
    assert gate[0].detail == "primary gate: missing equity"
    assert gate[0].points == 0.0


def test_gate_leaves_complete_primary_claim_standing() -> None:
    geometry = GeometryText(
        caption="Consolidated Balance Sheets",
        leadin="Balance sheet as of December 31, 2023.",
        stubs=(
            "Total assets",
            "Total current liabilities",
            "Total stockholders' equity",
        ),
    )
    (result,) = compete_filing([geometry], terms=_TERMS, edges=())
    assert result.claims == ("balance_sheet",)
    trail = result.scores["balance_sheet"].evidence
    assert not [entry for entry in trail if entry.channel == "gate"]


def test_gate_completes_over_cluster_mates() -> None:
    head = GeometryText(
        caption="Consolidated Balance Sheets",
        leadin="Balance sheet as of December 31, 2023.",
        stubs=("Total assets",),
        note_title="Financial Statements",
    )
    tail = GeometryText(
        stubs=("Total current liabilities", "Total stockholders' equity"),
        note_title="Financial Statements",
    )
    results = compete_filing([head, tail], terms=_TERMS, edges=())
    assert results[0].claims == ("balance_sheet",)


def test_gate_ignores_families_without_a_gate_set() -> None:
    geometry = GeometryText(
        caption="Operating Lease Liabilities",
        leadin="Lease liabilities mature as follows.",
        stubs=("2025", "Total undiscounted lease payments"),
    )
    (result,) = compete_filing([geometry], terms=_TERMS, edges=())
    assert result.claims == ("lease_maturity",)


def test_inherited_claim_cannot_resurrect_past_the_gate() -> None:
    first = GeometryText(
        caption="Statements of Changes in Equity",
        leadin="Statement of changes in equity for the year.",
        notehead="Changes in Equity",
        stubs=(
            "Balance, January 1, 2023",
            "Shares issued",
            "Accumulated other comprehensive income",
            "Balance, December 31, 2023",
        ),
        note_title="Equity",
    )
    fragment = GeometryText(
        stubs=("Shares issued", "Dividends declared"),
        note_title="Another Note",
    )
    results = compete_filing([first, fragment], terms=_TERMS, edges=())
    assert results[0].claims == ("equity_statement",)
    # The fragment inherits the claim (adjacent geometry), but its
    # own cluster carries no balance rows: the gate refuses it.
    assert results[1].claims == ()
    trail = results[1].scores["equity_statement"].evidence
    gate = [entry for entry in trail if entry.channel == "gate"]
    assert [entry.detail for entry in gate] == [
        "equity assignment: strictly dominated candidate",
        "primary gate: missing beginning_balances, ending_balances",
    ]
