"""Table-of-contents elimination: TOC-shaped tables as genre refusals.

A table inside the filing's cover TOC span is refused on that fact
alone; outside the span, a TOC-shaped table is refused on content —
page-reference rows spanning many namespaces, no currency amounts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.core.subjects.profiles import PROFILES
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    SIGNATURE_TERMS,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedRow, TypedTable
from edgar_sec.engine.tables.numeric_cells import (
    CURRENCY_TOKEN_RE,
    DECIMAL_AMOUNT_RE,
    is_numeric_cell,
)
from edgar_sec.engine.tables.toc.patterns import (
    RE_PART_REFERENCE,
    looks_like_toc_row,
    looks_like_toc_tabular,
    page_range_start,
    toc_title_parts,
)
from edgar_sec.foundation.text.patterns import (
    GROUPED_AMOUNT_CORE,
    RE_PAGE_REFERENCE,
)

MIN_ROWS = 3
_MIN_PAGE_SEQUENCE = 3
PAGE_REF_SHARE = 0.5
BREADTH_MIN = 4
NARROW_BREADTH_MIN = 2
NARROW_MIN_WEAK = 6

_PAGE_LETTER_RE = re.compile(r"^[A-Z]-\d+$")
_BARE_INT_RE = re.compile(r"^\d{1,3}$")
_REF_CELL_RE = re.compile(r"^(?:note|item)\s+\d+(?:\.\d+)*[A-Z]?\.?$", re.IGNORECASE)
_AMOUNT_RE = re.compile(rf"{GROUPED_AMOUNT_CORE}|{DECIMAL_AMOUNT_RE.pattern}")

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
    if any(RE_PAGE_REFERENCE.search(cell) for cell in cells):
        return True
    if any(_PAGE_LETTER_RE.match(cell) for cell in cells[1:]):
        return True
    return any(page_range_start(cell) is not None for cell in cells[1:])


def _weak_page_ref(cells: list[str]) -> int | None:
    """The row's page number when its trailing cells are only references."""
    if len(cells) < 2 or _row_money(cells):
        return None
    page: int | None = None
    for cell in cells[1:]:
        if _BARE_INT_RE.match(cell):
            page = int(cell)
        elif _PAGE_LETTER_RE.match(cell):
            page = int(cell.split("-", 1)[1])
        elif page_range_start(cell) is not None:
            page = page_range_start(cell)
        elif not _REF_CELL_RE.match(cell):
            return None
    return page


def _increasing(pages: list[int]) -> bool:
    if len(pages) < _MIN_PAGE_SEQUENCE or len(set(pages)) < _MIN_PAGE_SEQUENCE:
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


def page_ref_cell(cell: str) -> bool:
    """One cell that carries only a page or section reference."""
    cell = cell.strip()
    return bool(
        _BARE_INT_RE.match(cell)
        or _REF_CELL_RE.match(cell)
        or _PAGE_LETTER_RE.match(cell)
        or page_range_start(cell) is not None
    )


def grid_page_ref_share(rows: tuple[tuple[str, ...], ...]) -> float:
    """The page-reference row share over raw grid rows.

    The grid-level mirror of :func:`toc_signals`: strong rows and
    weak rows whose page numbers increase, over nonblank rows.
    """
    strong = 0
    weak_pages: list[int] = []
    total = 0
    for row in rows:
        cells = [cell.strip() for cell in row if cell.strip()]
        if not cells:
            continue
        total += 1
        if _strong_page_ref(cells):
            strong += 1
            continue
        if RE_PART_REFERENCE.search(cells[0]) and not any(
            is_numeric_cell(cell) for cell in cells[1:]
        ):
            strong += 1
            continue
        page = _weak_page_ref(cells)
        if page is not None:
            weak_pages.append(page)
    weak = len(weak_pages) if _increasing(weak_pages) else 0
    return (strong + weak) / total if total else 0.0


_TITLE_FAMILY_NAMES: tuple[str, ...] = tuple(p.family for p in PROFILES)


def _title_families(title: str) -> tuple[str, ...]:
    """The families a note title names: the family's own name in the
    title's words, or one of its caption terms where it carries any."""
    text = normalize_text(title)
    return tuple(
        sorted(
            family
            for family in _TITLE_FAMILY_NAMES
            if family.replace("_", " ") in text
            or any(term in text for term in _FAMILY_TERMS.get(family, ()))
        )
    )


def toc_refusal(table: TypedTable) -> TocRefusal | None:
    """Refuse inside the TOC span on that fact; on a TOC-formed note
    title naming families the table's own labels do not; else on shape."""
    signals = toc_signals(table)
    shape = (
        f"{signals.page_ref_rows}/{signals.rows} page-reference rows, "
        f"families {', '.join(signals.families) or 'none'}"
    )
    if table.context.in_toc_span:
        return TocRefusal(f"toc refused (cover span): {shape}", signals)
    note = table.context.note
    if note is not None and note.title and toc_title_parts(note.title):
        title_families = _title_families(note.title)
        own_families = _title_families(" ".join(row.label for row in table.rows))
        if title_families and not set(title_families) & set(own_families):
            return TocRefusal(
                f"toc refused (title): note title {note.title!r} names "
                f"{', '.join(title_families)}; {shape}",
                signals,
            )
    if not signals.shaped:
        return None
    if signals.currency_present:
        return None
    if len(signals.families) >= BREADTH_MIN:
        return TocRefusal(f"toc refused (content): {shape}", signals)
    if (
        len(signals.families) >= NARROW_BREADTH_MIN
        and signals.strong_rows >= 1
        and signals.weak_rows >= NARROW_MIN_WEAK
    ):
        return TocRefusal(f"toc refused (content, narrow): {shape}", signals)
    return None
