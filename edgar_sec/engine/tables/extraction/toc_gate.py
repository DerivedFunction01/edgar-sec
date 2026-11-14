"""Table-of-contents elimination: TOC-shaped tables as genre refusals.

A TOC-shaped table among a filing's first tables is refused outright;
a later one is refused on content — page-reference rows spanning many
family namespaces while carrying no currency amounts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.signature_profiles import SIGNATURE_TERMS
from edgar_sec.engine.tables.extraction.typed_rows import TypedRow, TypedTable
from edgar_sec.engine.tables.numeric_cells import CURRENCY_TOKEN_RE
from edgar_sec.engine.tables.toc.patterns import (
    RE_PART_REFERENCE,
    looks_like_toc_row,
    looks_like_toc_tabular,
)

EARLY_TABLE_INDEX = 10
MIN_ROWS = 3
PAGE_REF_SHARE = 0.5
BREADTH_MIN = 4
_PAGE_MAX = 999

_PAGE_TOKEN_RE = re.compile(r"\bpage\s*(?:no\.?\s*)?[A-Z]?-?\d+", re.IGNORECASE)
_PAGE_LETTER_RE = re.compile(r"^[A-Z]-\d+$")
_BARE_INT_RE = re.compile(r"^\d{1,3}$")
_REF_CELL_RE = re.compile(r"^(?:note|item)\s+\d+(?:\.\d+)*[A-Z]?\.?$", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\d,\d{3}|\d+\.\d+")

_TERM_SETS: dict[str, set[str]] = {}
for _term in SIGNATURE_TERMS:
    if _term.channel in ("caption", "stub") and len(_term.term) >= 4:
        _TERM_SETS.setdefault(_term.family, set()).add(normalize_text(_term.term))
_FAMILY_TERMS: dict[str, tuple[str, ...]] = {
    family: tuple(terms) for family, terms in _TERM_SETS.items()
}


@dataclass(frozen=True, slots=True)
class TocSignals:
    """One table's TOC-shape measurements, carried on the refusal."""

    rows: int
    strong_rows: int
    weak_rows: int
    currency_present: bool
    families: tuple[str, ...]

    @property
    def page_ref_rows(self) -> int:
        return self.strong_rows + self.weak_rows

    @property
    def shaped(self) -> bool:
        if self.rows < MIN_ROWS:
            return False
        return self.page_ref_rows / self.rows >= PAGE_REF_SHARE


@dataclass(frozen=True, slots=True)
class TocRefusal:
    """One TOC-shaped table refused at the genre seat."""

    detail: str
    signals: TocSignals


def _cells(row: TypedRow) -> list[str]:
    cells = [cell.strip() for cell in row.raw if cell.strip()]
    return cells or ([row.label] if row.label else [])


def _row_money(cells: list[str]) -> bool:
    return any(
        CURRENCY_TOKEN_RE.search(cell) or _AMOUNT_RE.search(cell) for cell in cells
    )


def _strong_page_ref(cells: list[str]) -> bool:
    line = " ".join(cells)
    if looks_like_toc_row(line) or looks_like_toc_tabular(line):
        return True
    if any(_PAGE_TOKEN_RE.search(cell) for cell in cells):
        return True
    return any(_PAGE_LETTER_RE.match(cell) for cell in cells[1:])


def _weak_page_ref(cells: list[str]) -> int | None:
    """The row's page number when its trailing cells are only references."""
    if len(cells) < 2 or _row_money(cells):
        return None
    page: int | None = None
    for cell in cells[1:]:
        if _BARE_INT_RE.match(cell):
            page = int(cell)
        elif not _REF_CELL_RE.match(cell):
            return None
    return page


def _increasing(pages: list[int]) -> bool:
    if len(pages) < MIN_ROWS or len(set(pages)) < MIN_ROWS:
        return False
    steps = sum(1 for a, b in zip(pages, pages[1:], strict=False) if b > a)
    return steps >= 0.8 * (len(pages) - 1)


def toc_signals(table: TypedTable) -> TocSignals:
    """Measure one table's TOC shape from its typed rows."""
    rows = [row for row in table.rows if _cells(row)]
    strong = 0
    weak_pages: list[int] = []
    weak_labels: list[str] = []
    strong_labels: list[str] = []
    currency = table.scale is not None
    for row in rows:
        cells = _cells(row)
        if _row_money(cells):
            currency = True
        if _strong_page_ref(cells):
            strong += 1
            strong_labels.append(row.label)
            continue
        if RE_PART_REFERENCE.search(cells[0]) and not row.values:
            strong += 1
            strong_labels.append(row.label)
            continue
        page = _weak_page_ref(cells)
        if page is not None:
            weak_pages.append(page)
            weak_labels.append(row.label)
    weak = len(weak_pages) if _increasing(weak_pages) else 0
    kept_labels = strong_labels + (weak_labels if weak else [])
    families = tuple(
        sorted(
            family
            for family, terms in _FAMILY_TERMS.items()
            if any(
                term in normalize_text(label) for label in kept_labels for term in terms
            )
        )
    )
    return TocSignals(
        rows=len(rows),
        strong_rows=strong,
        weak_rows=weak,
        currency_present=currency,
        families=families,
    )


def toc_refusal(table: TypedTable) -> TocRefusal | None:
    """Refuse a TOC-shaped table: outright among a filing's first
    tables; later only with no currency and at least BREADTH_MIN
    family namespaces across its page-reference rows."""
    signals = toc_signals(table)
    if not signals.shaped:
        return None
    shape = (
        f"{signals.page_ref_rows}/{signals.rows} page-reference rows, "
        f"families {', '.join(signals.families) or 'none'}"
    )
    if table.context.table_index < EARLY_TABLE_INDEX:
        return TocRefusal(f"toc refused (first tables): {shape}", signals)
    if not signals.currency_present and len(signals.families) >= BREADTH_MIN:
        return TocRefusal(f"toc refused (content): {shape}", signals)
    return None
