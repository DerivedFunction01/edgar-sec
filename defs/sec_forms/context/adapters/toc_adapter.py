"""TOC reference adapters (Phase C).

The existing :func:`defs.sec_forms.cover.toc.finder.find_toc_span` returns a
single :class:`defs.sec_forms.cover.toc.models.TocSpan` per filing. The
refactor introduces a list-based :class:`TocReference` view that:

- permits multiple TOCs (main, financial, note, exhibit indexes);
- carries candidate ``part``/``item`` text per entry;
- retains raw and normalized label separately;
- records page/anchor (HTML ``href``/``id``) and confidence;
- is fully deterministic given a soup snapshot.

Two adapters are provided:

- :func:`lift_toc_span_to_references` adapts the existing single-span result
  (or ``None``) to zero-or-more :class:`TocReference` records. This is the
  back-compat shim used by callers that already have a text-level ``TocSpan``.
- :func:`extract_toc_references` walks an HTML soup and emits a list of
  references parsed from the actual ``<a href="#…">`` anchors inside
  TOC-shaped tables. This is the new path; it does not require text
  normalization and handles multiple TOC regions.

The HTML path intentionally does *not* call the existing line-based
:func:`find_toc_span`; it operates on the soup directly so that anchor
links survive end-to-end.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from bs4 import BeautifulSoup

from defs.sec_forms.context.models import ContextEvidence, TocReference
from defs.sec_forms.cover.structure import SectionKind, parse_section_heading
from defs.sec_forms.cover.toc.analysis import normalize_for_matching
from defs.sec_forms.cover.toc.models import TocSpan
from defs.text.patterns import PAGE_NUMBER_CORE, RE_PAGE_NUMBER_SUFFIX

__all__ = [
    "TocEntry",
    "extract_toc_references",
    "lift_toc_span_to_references",
]

_PAGE_CELL_RE = re.compile(
    rf"^(?:(?:page|pg\.?)\s*)?(?P<page>(?:[A-Za-z][-–—])?{PAGE_NUMBER_CORE})\s*$",
    re.IGNORECASE,
)
_PAGE_INLINE_RE = re.compile(
    rf"\b(?:page|pg\.?)\s*(?P<page>{PAGE_NUMBER_CORE})\b",
    re.IGNORECASE,
)
_PAGE_LEADER_SUFFIX_RE = re.compile(
    rf"\.{(2,)}\s*(?P<page>{PAGE_NUMBER_CORE})\s*$",
    re.IGNORECASE,
)


def _extract_page_number(cell_texts: list[str]) -> str | None:
    """Extract a page number from the trailing cell or inline text of a TOC row."""
    if not cell_texts:
        return None
    # 1. Dedicated column/cell in a multi-cell row (e.g. <td>5</td>, <td>Page 5</td>)
    if len(cell_texts) >= 2:
        cell_match = _PAGE_CELL_RE.search(cell_texts[-1].strip())
        if cell_match:
            return cell_match.group("page")
    # 2. Inline mention (e.g. "Item 1 ... Page 5")
    inline_match = _PAGE_INLINE_RE.search(cell_texts[-1])
    if inline_match:
        return inline_match.group("page")
    # 3. Dot-leader suffix (e.g. "Item 1. Business .......... 5")
    leader_match = _PAGE_LEADER_SUFFIX_RE.search(cell_texts[-1])
    if leader_match:
        return leader_match.group("page")
    return None


@dataclass(frozen=True, slots=True)
class TocEntry:
    """Internal view of one parsed TOC row before normalization."""

    label: str
    part: str | None
    item: str | None
    anchor: str | None
    page: str | None
    ordinal: int
    confidence: float


def _confidence_for(label: str) -> float:
    """A small, deterministic confidence heuristic for a TOC row.

    Anchored rows are strongest; numeric-only anchors are weakest.
    """
    if not label:
        return 0.0
    lowered = label.casefold()
    if "item" in lowered or "part" in lowered:
        return 0.9
    if any(token in lowered for token in ("note ", "notes ", "schedule")):
        return 0.8
    if "exhibit" in lowered:
        return 0.85
    return 0.6


def _row_candidate(
    label: str,
    anchor: str | None,
    page: str | None,
    ordinal: int,
) -> TocEntry:
    parsed = parse_section_heading(label)
    part = parsed.identifier if (parsed and parsed.kind == SectionKind.PART) else None
    item = parsed.identifier if (parsed and parsed.kind == SectionKind.ITEM) else None
    return TocEntry(
        label=label.strip(),
        part=part,
        item=item,
        anchor=anchor,
        page=page,
        ordinal=ordinal,
        confidence=_confidence_for(label),
    )


def _looks_like_toc_label(text: str) -> bool:
    """Cheap test for whether a row text resembles a TOC entry.

    A row qualifies when it contains ``item``/``part``/``page``/``exhibit``/
    ``note`` vocabulary, *or* when it ends in a plain numeric page number
    (canonical financial-statement index shape).
    """
    if not text:
        return False
    lowered = text.casefold()
    if parse_section_heading(text) is not None:
        return True
    if any(
        marker in lowered
        for marker in ("item ", "part ", "page", "exhibit", "note ", "notes ")
    ):
        return True
    last_token = lowered.rstrip().rsplit(" ", 1)[-1]
    return bool(RE_PAGE_NUMBER_SUFFIX.fullmatch(last_token) and len(last_token) <= 6)


def _collect_anchors(
    soup: BeautifulSoup, table: object
) -> Iterable[tuple[str, str | None, str | None]]:
    """Yield ``(label, anchor, page)`` tuples for each TOC row in ``table``."""
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        cell_texts = [
            re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
            for cell in cells
        ]
        cell_texts = [text for text in cell_texts if text]
        if not cell_texts:
            continue
        anchor_href: str | None = None
        anchor_link = row.find("a", href=True)
        if anchor_link is not None:
            anchor_href = anchor_link.get("href", "").lstrip("#") or None
        label = " ".join(cell_texts)
        if not _looks_like_toc_label(label):
            continue
        page = _extract_page_number(cell_texts)
        yield label, anchor_href, page


def extract_toc_references(
    soup: BeautifulSoup,
    *,
    document_id: str = "",
    min_rows: int = 2,
) -> tuple[TocReference, ...]:
    """Return all :class:`TocReference` records found in ``soup``.

    Walks every ``<table>`` whose flattened text contains ``page``/``item``/
    ``part`` vocabulary, then lifts each row into a typed reference. The
    function is independent of the existing line-based TOC detector and
    therefore supports multiple TOCs (main, financial, note, exhibit).
    """
    references: list[TocReference] = []
    ordinal = 0
    for table in soup.find_all("table"):
        rows = list(_collect_anchors(soup, table))
        if len(rows) < min_rows:
            continue
        for label, anchor, page in rows:
            ordinal += 1
            entry = _row_candidate(label, anchor, page, ordinal)
            evidence = (
                ContextEvidence(
                    name="toc_row",
                    strength=entry.confidence,
                    details=entry.label,
                ),
            )
            references.append(
                TocReference(
                    label=entry.label,
                    normalized_label=normalize_for_matching(entry.label),
                    part=entry.part,
                    item=entry.item,
                    anchor=entry.anchor,
                    ordinal=entry.ordinal,
                    confidence=entry.confidence,
                    page=entry.page,
                    evidence=evidence,
                )
            )
    return tuple(references)


def lift_toc_span_to_references(
    span: TocSpan | None,
    *,
    document_id: str = "",
) -> tuple[TocReference, ...]:
    """Adapt a text-level :class:`TocSpan` to typed references.

    The existing single-span detector does not surface row-level Part/Item
    labels, so the lifted references only carry the span's evidence and a
    synthetic ordinal. This is enough for the back-compat path; the new HTML
    adapter (:func:`extract_toc_references`) provides the fully populated
    rows.
    """
    _ = document_id
    if span is None:
        return ()
    evidence = tuple(
        ContextEvidence(
            name=item.name,
            strength=0.0,
            details=item.details,
            line=item.line,
        )
        for item in span.evidence
    )
    return (
        TocReference(
            label="(span)",
            normalized_label="",
            part=None,
            item=None,
            anchor=None,
            ordinal=0,
            confidence=span.confidence,
            page=None,
            evidence=evidence,
        ),
    )
