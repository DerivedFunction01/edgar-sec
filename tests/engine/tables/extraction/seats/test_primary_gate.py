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


_CF_OP = "Cash flows from operating activities"
_CF_INV = "Cash flows from investing activities"
_CF_FIN = "Cash flows from financing activities"
_CF_REC = "Net increase in cash and cash equivalents"


def _cf_claim_result():
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        CompetitionResult,
        FamilyScore,
    )
    from edgar_sec.engine.tables.extraction.seats.primary_gate import (
        apply_primary_gate,
    )

    result = CompetitionResult(
        claims=("cash_flow",),
        contested=(),
        scores={"cash_flow": FamilyScore("cash_flow", 50.0, {"stub": 50.0}, ())},
    )
    return apply_primary_gate, result


def test_cash_flow_gate_singleton_reconciliation_waived() -> None:
    apply_primary_gate, result = _cf_claim_result()
    geometry = GeometryText(stubs=(_CF_OP, _CF_INV, _CF_FIN))
    (gated,) = apply_primary_gate([geometry], [result])
    assert gated.claims == ("cash_flow",)


def test_cash_flow_gate_singleton_financing_waived() -> None:
    apply_primary_gate, result = _cf_claim_result()
    geometry = GeometryText(stubs=(_CF_OP, _CF_INV, _CF_REC))
    (gated,) = apply_primary_gate([geometry], [result])
    assert gated.claims == ("cash_flow",)


def test_cash_flow_gate_supplemental_schedule_waived() -> None:
    apply_primary_gate, result = _cf_claim_result()
    geometry = GeometryText(
        note_title="Statement of Cash Flows",
        stubs=(
            "Cash paid during the period for: Interest",
            "Non-cash investing activities:",
            "Non-cash financing activities:",
        ),
    )
    (gated,) = apply_primary_gate([geometry], [result])
    assert gated.claims == ("cash_flow",)


def test_cash_flow_gate_exactly_one_missing_any_cluster_size() -> None:
    apply_primary_gate, result = _cf_claim_result()
    head = GeometryText(stubs=(_CF_OP, _CF_INV), note_title="Notes")
    tail = GeometryText(stubs=(_CF_FIN,), note_title="Notes")
    gated = apply_primary_gate([head, tail], [result, result])
    assert gated[0].claims == ("cash_flow",)
    assert gated[1].claims == ("cash_flow",)


def test_cash_flow_gate_continuation_extension_completes() -> None:
    apply_primary_gate, result = _cf_claim_result()
    head = GeometryText(stubs=(_CF_OP,), note_title="Financial Statements")
    mid = GeometryText(stubs=(_CF_INV,), note_title="Financial Statements")
    continuation = GeometryText(
        caption="Cash flows from financing activities:",
        stubs=(_CF_FIN, "Cash and cash equivalents, beginning of period"),
        note_title="Financial Statements",
    )
    gated = apply_primary_gate([head, mid, continuation], [result, result, result])
    assert gated[0].claims == ("cash_flow",)


def test_cash_flow_gate_uncaptioned_break_still_refused() -> None:
    apply_primary_gate, result = _cf_claim_result()
    head = GeometryText(stubs=(_CF_OP,), note_title="Financial Statements")
    mid = GeometryText(stubs=(_CF_INV,), note_title="Financial Statements")
    other = GeometryText(
        caption="Supplemental schedule",
        stubs=(_CF_FIN, "Cash and cash equivalents, beginning of period"),
        note_title="Financial Statements",
    )
    gated = apply_primary_gate([head, mid, other], [result, result, result])
    assert gated[0].claims == ()
    gate = [
        entry
        for entry in gated[0].scores["cash_flow"].evidence
        if entry.channel == "gate"
    ]
    assert gate[0].detail == ("primary gate: missing financing, cash_reconciliation")


def test_cash_flow_gate_fund_form_drops_only_investing() -> None:
    apply_primary_gate, result = _cf_claim_result()
    head = GeometryText(
        stubs=(_CF_OP, "Increase (decrease) in net assets resulting from operations"),
        note_title="Notes",
    )
    tail = GeometryText(stubs=(_CF_FIN,), note_title="Notes")
    gated = apply_primary_gate([head, tail], [result, result])
    assert gated[0].claims == ()
    gate = [
        entry
        for entry in gated[0].scores["cash_flow"].evidence
        if entry.channel == "gate"
    ]
    assert gate[0].detail == "primary gate: missing cash_reconciliation"


def test_cash_flow_gate_two_missing_still_refused() -> None:
    apply_primary_gate, result = _cf_claim_result()
    head = GeometryText(stubs=(_CF_OP,), note_title="Notes")
    tail = GeometryText(stubs=(_CF_INV,), note_title="Notes")
    gated = apply_primary_gate([head, tail], [result, result])
    assert gated[0].claims == ()
    gate = [
        entry
        for entry in gated[0].scores["cash_flow"].evidence
        if entry.channel == "gate"
    ]
    assert gate[0].detail == ("primary gate: missing financing, cash_reconciliation")


def test_cash_flow_lead_veto_scoped_shapes() -> None:
    from edgar_sec.engine.tables.extraction.seats.primary_gate import (
        cash_flow_lead_veto_scoped,
    )

    assert cash_flow_lead_veto_scoped(
        GeometryText(stubs=(_CF_OP, _CF_INV, _CF_FIN, _CF_REC))
    )
    assert cash_flow_lead_veto_scoped(GeometryText(stubs=(_CF_OP, _CF_INV, _CF_REC)))
    assert cash_flow_lead_veto_scoped(
        GeometryText(
            note_title="Statement of Cash Flows",
            stubs=(
                "Cash paid during the period for: Interest",
                "Non-cash investing activities:",
                "Non-cash financing activities:",
            ),
        )
    )
    assert not cash_flow_lead_veto_scoped(GeometryText(stubs=(_CF_OP, _CF_INV)))


def test_cash_flow_gate_spine_pair_waived_any_cluster_size() -> None:
    apply_primary_gate, result = _cf_claim_result()
    head = GeometryText(stubs=(_CF_OP,), note_title="Notes")
    tail = GeometryText(stubs=(_CF_REC,), note_title="Notes")
    gated = apply_primary_gate([head, tail], [result, result])
    assert gated[0].claims == ("cash_flow",)
    assert gated[1].claims == ("cash_flow",)


def test_cash_flow_gate_spine_pair_singleton_waived() -> None:
    apply_primary_gate, result = _cf_claim_result()
    geometry = GeometryText(stubs=(_CF_OP, _CF_REC))
    (gated,) = apply_primary_gate([geometry], [result])
    assert gated.claims == ("cash_flow",)


def test_cash_flow_gate_non_spine_pair_still_refused() -> None:
    apply_primary_gate, result = _cf_claim_result()
    head = GeometryText(stubs=(_CF_OP,), note_title="Notes")
    tail = GeometryText(stubs=(_CF_FIN,), note_title="Notes")
    gated = apply_primary_gate([head, tail], [result, result])
    assert gated[0].claims == ()
    gate = [
        entry
        for entry in gated[0].scores["cash_flow"].evidence
        if entry.channel == "gate"
    ]
    assert gate[0].detail == ("primary gate: missing investing, cash_reconciliation")


def test_cash_flow_gate_three_present_spine_pair_not_invoked() -> None:
    apply_primary_gate, result = _cf_claim_result()
    head = GeometryText(stubs=(_CF_OP,), note_title="Notes")
    mid = GeometryText(stubs=(_CF_INV,), note_title="Notes")
    tail = GeometryText(stubs=(_CF_REC,), note_title="Notes")
    gated = apply_primary_gate([head, mid, tail], [result, result, result])
    assert gated[0].claims == ("cash_flow",)


def test_cash_flow_gate_reduced_missing_set_is_not_spine_pair() -> None:
    apply_primary_gate, result = _cf_claim_result()
    geometry = GeometryText(stubs=(_CF_OP,))
    (gated,) = apply_primary_gate([geometry], [result])
    assert gated.claims == ()
    gate = [
        entry for entry in gated.scores["cash_flow"].evidence if entry.channel == "gate"
    ]
    assert gate[0].detail == "primary gate: missing investing, financing"


def test_cash_flow_grantor_veto_scoped_shapes() -> None:
    from edgar_sec.engine.tables.extraction.seats.primary_gate import (
        cash_flow_grantor_veto_scoped,
    )

    marker = "Proceeds from gold bullion sold to pay expenses"
    assert cash_flow_grantor_veto_scoped(GeometryText(stubs=(_CF_OP, marker, _CF_REC)))
    assert cash_flow_grantor_veto_scoped(
        GeometryText(stubs=(_CF_OP, _CF_REC), lead_title="Gold Bullion Trust")
    )
    assert not cash_flow_grantor_veto_scoped(GeometryText(stubs=(_CF_OP, _CF_REC)))
    assert not cash_flow_grantor_veto_scoped(
        GeometryText(stubs=(_CF_OP, _CF_INV, _CF_FIN, _CF_REC), lead_title=marker)
    )
    assert not cash_flow_grantor_veto_scoped(GeometryText(stubs=(marker, _CF_REC)))
