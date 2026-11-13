"""Region derivation over synthetic filing contexts."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.context import SectionRef, TableContext
from edgar_sec.engine.tables.extraction.regions import (
    derive_regions,
    effective_regions,
)

_SIGNATURE_ROWS = (
    ("SIGNATURES",),
    (
        "Pursuant to the requirements of Section 13 or 15(d) of the "
        "Securities Exchange Act of 1934, the registrant has duly caused "
        "this report to be signed on its behalf by the undersigned.",
    ),
    (
        "By: /s/ Jane Roe",
        "Jane Roe",
        "President and Chief Executive Officer",
        "November 10, 2026",
    ),
)

_BODY_ROWS = (
    ("Consolidated Balance Sheets",),
    ("Cash and cash equivalents", "100"),
)


def _context(
    rows: tuple[tuple[str, ...], ...],
    *,
    section: SectionRef | None = None,
    region: str | None = None,
) -> TableContext:
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
    return TableContext(geometry=geometry, section=section, region=region)


def test_trailing_signature_table_is_signature_region() -> None:
    contexts = [
        _context(_BODY_ROWS, section=SectionRef("ITEM 8", "Financial Statements")),
        _context(_BODY_ROWS, section=SectionRef("ITEM 15", "Exhibits")),
        _context(_SIGNATURE_ROWS),
    ]
    assert derive_regions(contexts) == ("body", "body", "signature")


def test_front_matter_is_cover_and_exhibit_title_is_exhibit() -> None:
    contexts = [
        _context(_BODY_ROWS),
        _context(_BODY_ROWS, section=SectionRef("ITEM 1", "Business")),
        _context(_BODY_ROWS, section=SectionRef("ITEM 15", "Exhibit Index")),
    ]
    assert derive_regions(contexts) == ("cover", "body", "exhibit")


def test_stamped_region_wins_over_derivation() -> None:
    contexts = [
        _context(_BODY_ROWS, section=SectionRef("ITEM 8", "Financial Statements")),
        _context(_SIGNATURE_ROWS, region="body"),
    ]
    assert effective_regions(contexts) == ("body", "body")
