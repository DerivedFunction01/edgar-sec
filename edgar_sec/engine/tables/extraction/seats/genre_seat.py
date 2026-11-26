"""Genre seat: document furniture refused upstream of competition.

Furniture is discovered and refused here, at the genre layer,
from facts produced once in context production — never carried
as per-family imposters and never re-derived by a consumer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_COMPOSITION_TWIN,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.seats.section_gate import (
    ScopeRow,
    genre_refusal,
)
from edgar_sec.engine.tables.extraction.seats.toc_gate import (
    toc_refusal,
    toc_signals,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.engine.tables.toc.patterns import RE_ITEM_REFERENCE
from edgar_sec.foundation.regex.builder import build_alternation

PAGE_REF_SHARE_MIN = 0.5
BAND_NUMERIC_CELLS_MAX = 3
BAND_PAGE_REF_SHARE_MIN = 0.15
INDEX_NAMED_SHARE_MIN = 0.5
EXHIBIT_STUB_SHARE_MIN = 0.5
EXHIBIT_MIN_ROWS = 3
EMPTY_BODY_MAX_ROWS = 2
FOLIO_MAX_CELLS = 3
CLOSING_NUMERIC_CELLS_MIN = 4
CLOSING_DATA_ROWS_MIN = 3

FULL_REFUSAL_PREFIXES = (
    "toc refused",
    "closing refused",
    "band refused",
    "index refused",
    "exhibit index refused",
    "empty body refused",
    "folio refused",
    "presence refused",
)

_EXHIBIT_STUB_ALTERNATION = build_alternation(
    [r"\d{1,3}\.\d{1,2}\b", r"101\.[A-Z]{3}\b", r"EX[-\s]?\d", r"EXHIBIT\b"]
)
_EXHIBIT_STUB_RE = re.compile(rf"^(?:{_EXHIBIT_STUB_ALTERNATION})", re.IGNORECASE)
_INDEX_NAMED_TERMS = (
    "balance sheet",
    "income statement",
    "statement of",
    "statements of",
    "cash flow",
    "equity",
    "comprehensive income",
    "financial statements",
    "notes to",
    "exhibit",
    "schedule",
    "index",
    "contents",
)


def exhibit_stub_cell(cell: str) -> bool:
    """One first cell carrying an exhibit number or stub."""
    return bool(_EXHIBIT_STUB_RE.match(cell.strip()))


def index_named_label(label: str) -> bool:
    """One row label naming an item, a statement, or an index part."""
    text = normalize_text(label)
    return bool(RE_ITEM_REFERENCE.search(text)) or any(
        term in text for term in _INDEX_NAMED_TERMS
    )


@dataclass(frozen=True, slots=True)
class GenreFacts:
    """The genre facts one geometry carries, from context production."""

    in_toc_span: bool = False
    in_closing_span: bool = False
    closing_kind: str | None = None
    front_matter: bool = False
    note_seated: bool = False
    numeric_cells: int = 0
    data_rows: int = 0
    grid_rows: int = 0
    max_row_cells: int = 0
    index_named_share: float = 0.0
    page_ref_share: float = 0.0
    page_ref_only: bool = False
    exhibit_stub_share: float = 0.0

    @classmethod
    def from_context(cls, context) -> GenreFacts:
        """Carry one TableContext's produced facts, deriving nothing."""
        return cls(
            in_toc_span=context.in_toc_span,
            in_closing_span=context.in_closing_span,
            closing_kind=context.closing_kind,
            front_matter=context.front_matter,
            note_seated=context.note is not None,
            numeric_cells=context.numeric_cells,
            data_rows=context.data_rows,
            grid_rows=context.grid_rows,
            max_row_cells=context.max_row_cells,
            index_named_share=context.index_named_share,
            page_ref_share=context.page_ref_share,
            page_ref_only=context.page_ref_only,
            exhibit_stub_share=context.exhibit_stub_share,
        )

    @classmethod
    def from_geometry(cls, geometry) -> GenreFacts:
        """Carry one GeometryText's mirrored facts, deriving nothing."""
        return cls(
            in_toc_span=geometry.in_toc_span,
            in_closing_span=geometry.in_closing_span,
            closing_kind=geometry.closing_kind,
            front_matter=geometry.front_matter,
            note_seated=geometry.note_seated,
            numeric_cells=geometry.numeric_cells,
            data_rows=geometry.data_rows,
            grid_rows=geometry.grid_rows,
            max_row_cells=geometry.max_row_cells,
            index_named_share=geometry.index_named_share,
            page_ref_share=geometry.page_ref_share,
            page_ref_only=geometry.page_ref_only,
            exhibit_stub_share=geometry.exhibit_stub_share,
        )


@dataclass(frozen=True, slots=True)
class SeatRefusal:
    """One furniture geometry refused at the genre seat."""

    detail: str
    arm: str


def _index_refusal(facts: GenreFacts) -> SeatRefusal | None:
    if (
        facts.page_ref_share >= PAGE_REF_SHARE_MIN
        and facts.index_named_share >= INDEX_NAMED_SHARE_MIN
        and facts.page_ref_only
    ):
        return SeatRefusal(
            "index refused: page-reference rows naming items or "
            f"statements ({facts.page_ref_share:.2f} page-reference share, "
            f"{facts.index_named_share:.2f} named share)",
            "index",
        )
    return None


def _band_refusal(facts: GenreFacts) -> SeatRefusal | None:
    """Arm 4, scoped: front-matter band conjoined with a shape
    fact (tiny numeric body, or page references carried)."""
    if facts.front_matter and (
        facts.numeric_cells <= BAND_NUMERIC_CELLS_MAX
        or facts.page_ref_share >= BAND_PAGE_REF_SHARE_MIN
    ):
        return SeatRefusal(
            "band refused: front-matter geometry "
            f"({facts.numeric_cells} numeric cells, "
            f"{facts.page_ref_share:.2f} page-reference share)",
            "band",
        )
    return None


def _shape_refusal(facts: GenreFacts) -> SeatRefusal | None:
    """The content-shape arms, in seat order: exhibit, empty, folio,
    presence."""
    if (
        facts.grid_rows >= EXHIBIT_MIN_ROWS
        and facts.exhibit_stub_share >= EXHIBIT_STUB_SHARE_MIN
    ):
        return SeatRefusal(
            "exhibit index refused: exhibit-number stubs in "
            f"{facts.exhibit_stub_share:.2f} of {facts.grid_rows} rows",
            "exhibit_stub",
        )
    if 1 <= facts.grid_rows <= EMPTY_BODY_MAX_ROWS and facts.numeric_cells == 0:
        return SeatRefusal(
            f"empty body refused: {facts.grid_rows} rows, no numeric cells",
            "empty_body",
        )
    if facts.grid_rows == 1 and facts.max_row_cells <= FOLIO_MAX_CELLS:
        return SeatRefusal(
            f"folio refused: single row of {facts.max_row_cells} cells",
            "folio",
        )
    if facts.numeric_cells == 0 and facts.grid_rows >= 1 and not facts.note_seated:
        return SeatRefusal(
            "presence refused: no numeric cells and no note seat",
            "presence",
        )
    return None


def _statement_content(facts: GenreFacts) -> bool:
    """Statement content: a numeric grid, not a signature block."""
    return (
        facts.numeric_cells >= CLOSING_NUMERIC_CELLS_MIN
        and facts.data_rows >= CLOSING_DATA_ROWS_MIN
    )


def _facts_refusal(facts: GenreFacts) -> SeatRefusal | None:
    """The facts-only seat, in order: span, index, closing, band,
    shapes."""
    if facts.in_toc_span:
        return SeatRefusal("toc refused (cover span)", "toc_span")
    refusal = _index_refusal(facts)
    if refusal is not None:
        return refusal
    if facts.in_closing_span and not _statement_content(facts):
        return SeatRefusal(
            f"closing refused: {facts.closing_kind or 'closing'} region",
            "closing_span",
        )
    refusal = _band_refusal(facts)
    if refusal is not None:
        return refusal
    return _shape_refusal(facts)


def geometry_refusal(geometry) -> SeatRefusal | None:
    """Refuse one competition geometry on its carried facts alone."""
    refusal = _facts_refusal(GenreFacts.from_geometry(geometry))
    if refusal is not None and refusal.arm == "band":
        # Yield (priced, inventory Addendum 8): a passed
        # composition twin seats the geometry as a family's
        # own table; the front-matter band does not refuse it.
        if any(
            outcome.kind == TEST_COMPOSITION_TWIN and outcome.passed
            for outcome in getattr(geometry, "form_tests", ())
        ):
            return None
    return refusal


def table_refusal(table: TypedTable) -> SeatRefusal | None:
    """Refuse one typed table: TOC gate, index arm, closing, shapes."""
    toc = toc_refusal(table)
    if toc is not None:
        return SeatRefusal(toc.detail, "toc")
    facts = GenreFacts.from_context(table.context)
    signals = toc_signals(table)
    if (
        signals.shaped
        and facts.index_named_share >= INDEX_NAMED_SHARE_MIN
        and facts.page_ref_only
    ):
        return SeatRefusal(
            "index refused: page-reference rows naming items or "
            f"statements ({signals.page_ref_rows}/{signals.rows} "
            "page-reference rows, "
            f"{facts.index_named_share:.2f} named share)",
            "index",
        )
    if facts.in_closing_span and not _statement_content(facts):
        return SeatRefusal(
            f"closing refused: {facts.closing_kind or 'closing'} region",
            "closing_span",
        )
    refusal = _band_refusal(facts)
    if refusal is not None:
        return refusal
    return _shape_refusal(facts)


def apply_section_refusals(
    claims: list[str],
    contested: list[str],
    geometry,
    scopes: tuple[ScopeRow, ...],
) -> tuple[list[str], list[str]]:
    """Drop statement-family claims refused by section position."""
    if not scopes:
        return claims, contested
    kept: list[str] = []
    for family in claims:
        refusal = genre_refusal(
            scopes,
            family,
            geometry.section_form,
            geometry.section_part,
            geometry.section_item,
            geometry.section_title,
        )
        if refusal is None:
            kept.append(family)
    dropped = set(claims) - set(kept)
    return kept, [family for family in contested if family not in dropped]
