"""S2 stub routing: priced-form pins over specimen-shaped fixtures."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.classify import classify_filing
from edgar_sec.engine.tables.extraction.core.context import SectionRef, TableContext
from edgar_sec.engine.tables.extraction.seats.stub_routing import (
    TEXT_TERMS,
    StubSurfaces,
    carrier_text,
    evaluate_stub_routing,
    is_carrier_text,
    packet_surfaces,
    route_family,
    signature_hits,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)

CARRIER_ROWS = (
    ("Balance, January 1, 2019", "100"),
    ("Balance, December 31, 2019", "110"),
)
FAIR_VALUE_ROWS = (
    ("Balance, January 1, 2016", "1,000"),
    ("Assets classified as Level 3", "500"),
    ("Balance, December 31, 2016", "1,100"),
)
FAIR_VALUE_LEAD = (
    "The following table provides a reconciliation of assets measured "
    "at fair value on a recurring basis for which Level 3 inputs were "
    "used in determining fair value:"
)


def _table(
    rows: tuple[tuple[str, ...], ...],
    *,
    caption_stack: tuple[str, ...] = (),
    prose_before: str = "",
    form: str | None = "10-K",
    in_closing_span: bool = False,
    closing_kind: str | None = None,
    region: str | None = None,
) -> TypedTable:
    """Build one typed table from raw geometry rows."""
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
        caption_stack=caption_stack,
        prose_before=prose_before,
        section=SectionRef("ITEM 8", None, form, None) if form is not None else None,
        in_closing_span=in_closing_span,
        closing_kind=closing_kind,
        region=region,
    )
    return structure_table(context)


def test_vocabulary_counts_and_provenance_terms() -> None:
    """The derived vocabularies are the priced map's own terms."""
    assert len(TEXT_TERMS["equity_statement"]) == 139
    assert len(TEXT_TERMS["fair_value"]) == 202
    assert "accumulated" in TEXT_TERMS["equity_statement"]
    assert "additional" in TEXT_TERMS["equity_statement"]
    assert "fair value" in TEXT_TERMS["fair_value"]
    assert "(level 3)" in TEXT_TERMS["fair_value"]
    assert "acquisitions" in TEXT_TERMS["fair_value"]


def test_carrier_shape() -> None:
    """The tight stub lives inside one cell, day one of a month."""
    assert is_carrier_text("Balance, January 1, 2021 | 100")
    assert is_carrier_text("Beginning balance at March 1, 2020")
    assert not is_carrier_text("Balance at December 31, 2021 | 110")
    assert not is_carrier_text("Balance | January 1, 2021")
    assert not is_carrier_text("Total revenues | 5")
    text = carrier_text((("Balance, January 1, 2021", "100"),))
    assert text == "Balance, January 1, 2021 | 100"


def test_packet_surfaces() -> None:
    """The packet reading keeps caption, lead, first-cell stub."""
    surfaces = packet_surfaces(
        ("Note 5",), "lead text", "Assets | 5\nBalance, January 1, 2021 | 100"
    )
    assert surfaces.caption == "Note 5"
    assert surfaces.lead == "lead text"
    assert surfaces.stub == "Assets \nBalance, January 1, 2021 "


def test_signature_hits_exact_terms() -> None:
    """Distinct map terms present over the surfaces are the hits."""
    equity = signature_hits(StubSurfaces("", "accumulated additional zebra", ""))
    assert set(equity["equity_statement"]) == {"accumulated", "additional"}
    assert equity["fair_value"] == ()
    fair = signature_hits(
        StubSurfaces("", "acquisitions (level 3) fair value zebra", "")
    )
    assert set(fair["fair_value"]) == {
        "acquisitions",
        "(level 3)",
        "level 3",
        "fair value",
    }
    assert fair["equity_statement"] == ()
    empty = signature_hits(StubSurfaces("", "zebra quux", "zebra item"))
    assert empty["equity_statement"] == ()
    assert empty["fair_value"] == ()


def test_route_family_cells() -> None:
    """Single hit routes; dual routes by argmax; a tie seats none."""
    assert (
        route_family({"equity_statement": ("a",), "fair_value": ()})
        == "equity_statement"
    )
    assert (
        route_family({"equity_statement": ("a",), "fair_value": ("b", "c")})
        == "fair_value"
    )
    assert (
        route_family({"equity_statement": ("a", "b", "c"), "fair_value": ("d",)})
        == "equity_statement"
    )
    assert route_family({"equity_statement": ("a",), "fair_value": ("b",)}) is None
    assert route_family({"equity_statement": (), "fair_value": ()}) is None


def test_evaluate_routes_fair_value_diagnostic_shape() -> None:
    """The priced diagnostic specimen's shape routes to fair value."""
    table = _table(FAIR_VALUE_ROWS, prose_before=FAIR_VALUE_LEAD)
    outcome = evaluate_stub_routing(table)
    assert outcome is not None
    assert outcome.family == "fair_value"
    assert outcome.fair_value_hits >= 2
    assert outcome.equity_hits < outcome.fair_value_hits


def test_evaluate_dual_hit_argmax() -> None:
    """A dual-hit carrier seats the single argmax claim."""
    rows = CARRIER_ROWS + (("Accumulated deficit", "3"),)
    table = _table(rows, prose_before="acquisitions (level 3) fair value")
    outcome = evaluate_stub_routing(table)
    assert outcome is not None
    assert outcome.family == "fair_value"
    assert outcome.equity_hits >= 1
    assert outcome.fair_value_hits > outcome.equity_hits
    assert "argmax" in outcome.detail


def test_evaluate_scope_and_shape_refusals() -> None:
    """Quarterly, unformed, term-free, and non-carrier shapes stay."""
    amended = _table(FAIR_VALUE_ROWS, prose_before=FAIR_VALUE_LEAD, form="10-K/A")
    outcome = evaluate_stub_routing(amended)
    assert outcome is not None and outcome.family == "fair_value"
    quarterly = _table(FAIR_VALUE_ROWS, prose_before=FAIR_VALUE_LEAD, form="10-Q")
    assert evaluate_stub_routing(quarterly) is None
    unformed = _table(FAIR_VALUE_ROWS, prose_before=FAIR_VALUE_LEAD, form=None)
    assert evaluate_stub_routing(unformed) is None
    assert evaluate_stub_routing(_table(CARRIER_ROWS)) is None
    non_carrier = _table(
        (("Assets classified as Level 3", "5"), ("Total assets", "9")),
        prose_before="measured at fair value",
    )
    assert evaluate_stub_routing(non_carrier) is None


def test_filing_routes_closing_refused_carrier() -> None:
    """A closing-span refused carrier is claimed at stub_routing."""
    table = _table(
        FAIR_VALUE_ROWS,
        prose_before=FAIR_VALUE_LEAD,
        in_closing_span=True,
        closing_kind="signatures",
    )
    results, _scores = classify_filing([table])
    assert results[0].family == "fair_value"
    assert results[0].tier == "stub_routing"
    assert any(ev.group == "stub_routing" for ev in results[0].evidence)


def test_filing_keeps_quarterly_closing_refused_carrier() -> None:
    """The same refused carrier in a 10-Q stays at the residual."""
    table = _table(
        FAIR_VALUE_ROWS,
        prose_before=FAIR_VALUE_LEAD,
        form="10-Q",
        in_closing_span=True,
        closing_kind="signatures",
    )
    results, _scores = classify_filing([table])
    assert results[0].family == "other"
    assert results[0].tier == "genre_refusal"


def test_filing_routes_residual_carrier() -> None:
    """A cascade-residual equity carrier is claimed by its lead."""
    rows = CARRIER_ROWS + (("Accumulated deficit", "3"),)
    table = _table(rows, prose_before="accumulated additional paid-in capital")
    results, _scores = classify_filing([table])
    assert results[0].family == "equity_statement"
    assert results[0].tier == "stub_routing"


def test_filing_keeps_signature_region_carrier() -> None:
    """A signature-region carrier is outside the routing scope."""
    table = _table(
        FAIR_VALUE_ROWS,
        prose_before=FAIR_VALUE_LEAD,
        in_closing_span=True,
        closing_kind="signatures",
        region="signature",
    )
    results, _scores = classify_filing([table])
    assert results[0].family == "other"
    assert results[0].tier == "region"


def test_filing_leaves_claimed_table_untouched() -> None:
    """A table the cascade claims keeps its own assignment."""
    rows = (
        ("Assets", ""),
        ("Cash and cash equivalents", "5"),
        ("Total assets", "9"),
        ("Liabilities and Stockholders' Equity", ""),
        ("Total liabilities", "4"),
        ("Total liabilities and stockholders' equity", "9"),
    )
    results, _scores = classify_filing([_table(rows)])
    assert results[0].family == "balance_sheet"
    assert results[0].tier != "stub_routing"
