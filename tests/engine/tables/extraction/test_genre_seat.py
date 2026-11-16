"""Genre seat tests: furniture refused upstream, on both paths.

Grids mirror named Step 6 specimen shapes; facts ride the context.
"""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.location import section_scopes
from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.classify import classify_table
from edgar_sec.engine.tables.extraction.competition import (
    GeometryText,
    compete,
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.context import (
    NoteRef,
    SectionRef,
    TableContext,
)
from edgar_sec.engine.tables.extraction.context_production import _grid_facts
from edgar_sec.engine.tables.extraction.genre_seat import (
    geometry_refusal,
    table_refusal,
)
from edgar_sec.engine.tables.extraction.policy import ClassificationPolicy
from edgar_sec.engine.tables.extraction.section_gate import (
    SectionScope,
    genre_refusal,
    section_scope,
)
from edgar_sec.engine.tables.extraction.typed_rows import structure_table

SCOPES = section_scopes()
POLICY = ClassificationPolicy(section_scopes=SCOPES)

_SIGNATURE = (
    ("By:", "/s/ Jane A. Doe"),
    ("Name:", "Jane A. Doe"),
    ("Title:", "Chief Executive Officer"),
    ("Date:", "March 1, 2026"),
    ("By:", "/s/ John B. Roe"),
    ("Name:", "John B. Roe"),
    ("Title:", "Chief Financial Officer"),
)

_EXHIBIT_INDEX = (
    ("101.INS", "XBRL Instance Document"),
    ("101.SCH", "XBRL Taxonomy Extension Schema"),
    ("101.CAL", "XBRL Taxonomy Extension Calculation Linkbase"),
    ("31.1", "Certification of Chief Executive Officer"),
    ("32.1", "Certification of Chief Financial Officer"),
    ("104", "Cover Page Interactive Data File"),
)

_STATEMENT_INDEX = (
    ("Consolidated Balance Sheets", "F-3"),
    ("Consolidated Statements of Operations", "F-5"),
    ("Consolidated Statements of Comprehensive Income", "F-6"),
    ("Consolidated Statements of Cash Flows", "F-7"),
    ("Notes to Consolidated Financial Statements", "F-9"),
)

_BALANCE_SHEET = (
    ("Cash and cash equivalents", "$", "1,234"),
    ("Accounts receivable, net", "", "567"),
    ("Property and equipment, net", "", "890"),
    ("Total assets", "", "2,691"),
    ("Accounts payable", "", "345"),
    ("Total current liabilities", "", "345"),
    ("Total liabilities and stockholders' equity", "", "2,691"),
)


def _context(grid, **facts) -> TableContext:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=tuple(tuple(row) for row in grid),
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    produced = _grid_facts([list(row) for row in grid])
    produced.update(facts)
    return TableContext(geometry=geometry, **produced)


def _geometry(grid, **facts) -> GeometryText:
    table = structure_table(_context(grid, **facts))
    return geometry_text_from_table(table)


def _refusal_detail(grid, **facts) -> str | None:
    result = classify_table(structure_table(_context(grid, **facts)))
    if result.tier != "genre_refusal":
        return None
    return next(
        entry.detail for entry in result.evidence if entry.group == "genre_refusal"
    )


def test_grid_facts_measure_the_signature_grid() -> None:
    facts = _grid_facts([list(row) for row in _SIGNATURE])
    assert facts["grid_rows"] == 7
    assert facts["numeric_cells"] == 0
    assert facts["data_rows"] == 0


def test_signature_block_refused_by_presence_on_both_paths() -> None:
    detail = _refusal_detail(_SIGNATURE)
    assert detail is not None and detail.startswith("presence refused")
    assert compete(_geometry(_SIGNATURE)).claims == ()


def test_exhibit_index_refused_by_stub_shape_on_both_paths() -> None:
    detail = _refusal_detail(_EXHIBIT_INDEX)
    assert detail is not None and detail.startswith("exhibit index refused")
    assert compete(_geometry(_EXHIBIT_INDEX)).claims == ()


def test_statement_index_refused_by_index_arm_on_both_paths() -> None:
    detail = _refusal_detail(_STATEMENT_INDEX)
    assert detail is not None and detail.startswith(("index refused", "toc refused"))
    geometry = _geometry(_STATEMENT_INDEX)
    refusal = geometry_refusal(geometry)
    assert refusal is not None and refusal.detail.startswith("index refused")
    assert compete(geometry).claims == ()


def test_toc_span_fact_refuses_a_statement_grid() -> None:
    detail = _refusal_detail(_BALANCE_SHEET, in_toc_span=True)
    assert detail is not None and detail.startswith("toc refused")
    assert compete(_geometry(_BALANCE_SHEET, in_toc_span=True)).claims == ()


def test_closing_span_fact_refuses_a_statement_grid() -> None:
    facts = {"in_closing_span": True, "closing_kind": "signatures"}
    detail = _refusal_detail(_BALANCE_SHEET, **facts)
    assert detail is not None and detail.startswith("closing refused")
    assert compete(_geometry(_BALANCE_SHEET, **facts)).claims == ()


def test_folio_row_refused() -> None:
    detail = _refusal_detail((("Form 10-K", "2024", "12"),))
    assert detail is not None and detail.startswith("folio refused")


def test_heading_fragment_refused_by_empty_body_even_note_seated() -> None:
    grid = (("Note 12 — Commitments and Contingencies",), ("(in thousands)",))
    context = _context(grid, note=NoteRef(12, "Note 12", "Commitments"))
    refusal = table_refusal(structure_table(context))
    assert refusal is not None and refusal.detail.startswith("empty body refused")


def test_note_seated_zero_numeric_table_is_not_presence_refused() -> None:
    grid = (
        ("Valuation technique", "Unobservable inputs", "Range"),
        ("Market approach", "Discount rate", "Low to high"),
        ("Income approach", "Growth rate", "Low to high"),
        ("Cost approach", "Obsolescence", "Low to high"),
    )
    context = _context(grid, note=NoteRef(3, "Note 3", "Fair Value Measurement"))
    assert table_refusal(structure_table(context)) is None
    geometry = geometry_text_from_table(structure_table(context))
    assert geometry_refusal(geometry) is None


def test_true_balance_sheet_is_not_refused() -> None:
    context = _context(_BALANCE_SHEET)
    assert table_refusal(structure_table(context)) is None
    result = classify_table(structure_table(context))
    assert result.tier != "genre_refusal"
    assert "balance_sheet" in compete(_geometry(_BALANCE_SHEET)).claims


def test_directors_scope_is_declared_and_refuses_statement_families() -> None:
    assert section_scope(SCOPES, "10-K", None, "ITEM 10") is SectionScope.DIRECTORS
    refusal = genre_refusal(SCOPES, "balance_sheet", "10-K", None, "ITEM 10")
    assert refusal is not None and "directors" in refusal.detail
    assert genre_refusal(SCOPES, "debt", "10-K", None, "ITEM 10") is None


def test_directors_position_refuses_on_both_paths() -> None:
    section = SectionRef(
        "ITEM 10",
        "Directors, Executive Officers and Corporate Governance",
        "10-K",
        "PART III",
    )
    context = _context(_BALANCE_SHEET, section=section)
    result = classify_table(structure_table(context), POLICY)
    assert result.tier == "genre_refusal"
    assert "directors" in next(
        entry.detail for entry in result.evidence if entry.group == "genre_refusal"
    )
    geometry = _geometry(_BALANCE_SHEET, section=section)
    assert "balance_sheet" not in compete(geometry, scopes=SCOPES).claims
    assert "balance_sheet" in compete(geometry).claims


def test_front_matter_fact_is_carried() -> None:
    geometry = _geometry(_BALANCE_SHEET, front_matter=True)
    assert geometry.front_matter


def test_front_loaded_balance_sheet_is_not_band_refused() -> None:
    geometry = _geometry(_BALANCE_SHEET, front_matter=True)
    assert geometry_refusal(geometry) is None
    assert "balance_sheet" in compete(geometry).claims


_COVER_SECURITIES = (
    ("Title of each class", "Trading Symbol(s)", "Name of each exchange"),
    ("Common stock, $0.001 par value", "None", "None"),
    ("Preferred stock, $0.001 par value", "None", "None"),
)

_CONTENTS_PAGE = (
    ("Item 1. Business", "3"),
    ("Item 1A. Risk Factors", "12"),
    ("Business Overview", "", "6,789"),
    ("Risk Factors Summary", ""),
    ("Properties and Locations", ""),
    ("Legal Proceedings", ""),
    ("Market Information", "", "1,234"),
    ("Selected Consolidated Data", "", "2,345"),
    ("Management Discussion", "", "3,456"),
    ("Quantitative Disclosures", "", "4,567"),
    ("Controls and Procedures", "", "5,678"),
)


def test_cover_securities_table_refused_by_scoped_band() -> None:
    facts = {"front_matter": True, "numeric_cells": 3}
    detail = _refusal_detail(_COVER_SECURITIES, **facts)
    assert detail is not None and detail.startswith("band refused")
    geometry = _geometry(_COVER_SECURITIES, **facts)
    refusal = geometry_refusal(geometry)
    assert refusal is not None and refusal.arm == "band"
    assert compete(geometry).claims == ()


def test_contents_page_refused_by_scoped_band() -> None:
    facts = {"front_matter": True, "numeric_cells": 8, "page_ref_share": 0.18}
    detail = _refusal_detail(_CONTENTS_PAGE, **facts)
    assert detail is not None and detail.startswith("band refused")
    geometry = _geometry(_CONTENTS_PAGE, **facts)
    refusal = geometry_refusal(geometry)
    assert refusal is not None and refusal.arm == "band"
    assert compete(geometry).claims == ()


def test_front_matter_note_table_is_not_band_refused() -> None:
    grid = (
        ("Derivative", "Notional", "Fair value"),
        ("Interest rate swaps", "12,000", "345"),
        ("Foreign exchange contracts", "8,000", "123"),
        ("Commodity contracts", "5,000", "67"),
        ("Total derivatives", "25,000", "535"),
        ("Netting adjustment", "", "(12)"),
    )
    facts = {"front_matter": True, "numeric_cells": 12}
    geometry = _geometry(grid, **facts)
    assert geometry_refusal(geometry) is None
