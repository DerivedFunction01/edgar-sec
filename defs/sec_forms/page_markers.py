"""Detection and analysis of page-marker spans across SEC filing representations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PageMarkerKind:
    """Stable names for supported page-marker shapes."""

    SGML = "sgml"
    DASHED_NUMBER = "dashed_number"
    PAGE_NUMBER = "page_number"
    NUMBER_OF_TOTAL = "number_of_total"
    PAGE_NUMBER_OF_TOTAL = "page_number_of_total"
    LETTER_NUMBER = "letter_number"
    HTML_NODE = "html_node"
    TABLE_FOOTER = "table_footer"


class PageMarkerAction(StrEnum):
    """Decision actions for page marker post-processing."""

    REMOVE = "remove"
    NORMALIZE = "normalize"
    PRESERVE = "preserve"


@dataclass(frozen=True, slots=True)
class PageMarkerSpan:
    """A detected page marker and its source span (backward-compatible tuple format)."""

    start: int
    end: int
    text: str
    kind: str
    page_number: int | None = None
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class PageMarker:
    """A detected page marker and its representation metadata."""

    start: int
    end: int
    text: str
    kind: str
    page_number: int | None = None
    page_count: int | None = None
    representation: str = "ascii"
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class PageMarkerDecision:
    """Action decision for a detected page marker."""

    marker: PageMarker
    action: PageMarkerAction
    reason: str
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class PageMarkerAnalysis:
    """Analysis result containing detected page markers, decisions, and boundaries."""

    markers: tuple[PageMarker, ...]
    decisions: tuple[PageMarkerDecision, ...]
    page_boundaries: tuple[int, ...]
    representation: str = "ascii"
    source_text: str = ""


# Regex patterns for line-oriented and inline page markers
_RE_PAGE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^\s*page\s+(?P<page>\d+)\s+of\s+(?P<count>\d+)\s*$", re.IGNORECASE
)
_RE_NUMBER_OF_TOTAL = re.compile(r"(?im)^\s*(?P<page>\d+)\s+of\s+(?P<count>\d+)\s*$")
_RE_PAGE_NUMBER = re.compile(r"(?im)^\s*page\s+(?P<page>\d+)\s*$", re.IGNORECASE)
_RE_DASHED_NUMBER = re.compile(r"(?im)^\s*-\s*(?P<page>\d+)\s*-\s*$")
_RE_LETTER_NUMBER = re.compile(r"(?im)^\s*(?P<prefix>[A-Z])\s*-\s*(?P<page>\d+)\s*$")
_RE_SGML_LINE = re.compile(
    r"(?im)^\s*<\/?PAGE\b[^>]*>\s*(?P<page>\d+)?\s*(?:<\/?PAGE\b[^>]*>)?\s*$"
)
_RE_SGML_INLINE = re.compile(r"(?i)<\/?PAGE\b[^>]*>")


_PAGE_MARKER_PATTERNS = (
    (PageMarkerKind.PAGE_NUMBER_OF_TOTAL, _RE_PAGE_NUMBER_OF_TOTAL),
    (PageMarkerKind.NUMBER_OF_TOTAL, _RE_NUMBER_OF_TOTAL),
    (PageMarkerKind.PAGE_NUMBER, _RE_PAGE_NUMBER),
    (PageMarkerKind.DASHED_NUMBER, _RE_DASHED_NUMBER),
    (PageMarkerKind.LETTER_NUMBER, _RE_LETTER_NUMBER),
    (PageMarkerKind.SGML, _RE_SGML_LINE),
    (PageMarkerKind.SGML, _RE_SGML_INLINE),
)


def _validate_sequence(numbers: list[int]) -> bool:
    """Return True if numbers form a plausibly monotonic page sequence."""
    if len(numbers) < 2:
        return False
    increasing = 0
    for i in range(len(numbers) - 1):
        diff = numbers[i + 1] - numbers[i]
        if 0 < diff <= 3:
            increasing += 1
    return increasing >= len(numbers) // 2


def find_page_markers(
    text: str, *, allow_letter_number: bool = False
) -> tuple[PageMarkerSpan, ...]:
    """Return non-overlapping page-marker spans in source order.

    Preserves the legacy contract for backward compatibility.
    """
    analysis = analyze_page_markers(
        text, allow_letter_number=allow_letter_number, representation="ascii"
    )
    return tuple(
        PageMarkerSpan(
            start=m.start,
            end=m.end,
            text=m.text,
            kind=(
                PageMarkerKind.NUMBER_OF_TOTAL
                if m.kind == PageMarkerKind.PAGE_NUMBER_OF_TOTAL
                else m.kind
            ),
            page_number=m.page_number,
            page_count=m.page_count,
        )
        for m in analysis.markers
    )


def analyze_page_markers(
    document: str,
    context: dict[str, Any] | None = None,
    *,
    representation: str = "ascii",
    allow_letter_number: bool = False,
) -> PageMarkerAnalysis:
    """Detect and classify page markers across full document representations."""
    if not document:
        return PageMarkerAnalysis(
            markers=(),
            decisions=(),
            page_boundaries=(),
            representation=representation,
            source_text=document,
        )

    occupied: list[tuple[int, int]] = []
    markers: list[PageMarker] = []

    for kind, pattern in _PAGE_MARKER_PATTERNS:
        if kind == PageMarkerKind.LETTER_NUMBER and not allow_letter_number:
            continue
        for match in pattern.finditer(document):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            occupied.append(span)
            groupdict = match.groupdict() if hasattr(match, "groupdict") else {}
            page = groupdict.get("page")
            count = groupdict.get("count")
            markers.append(
                PageMarker(
                    start=span[0],
                    end=span[1],
                    text=match.group(0),
                    kind=kind,
                    page_number=int(page) if page and page.isdigit() else None,
                    page_count=int(count) if count and count.isdigit() else None,
                    representation=representation,
                    confidence=0.95 if kind != PageMarkerKind.LETTER_NUMBER else 0.7,
                )
            )

    markers.sort(key=lambda m: m.start)

    # Sequence validation
    page_numbers = [m.page_number for m in markers if m.page_number is not None]
    has_valid_seq = _validate_sequence(page_numbers)

    decisions: list[PageMarkerDecision] = []
    for marker in markers:
        if marker.kind == PageMarkerKind.SGML:
            decisions.append(
                PageMarkerDecision(
                    marker=marker,
                    action=PageMarkerAction.REMOVE,
                    reason="sgml_page_tag",
                    confidence=1.0,
                )
            )
        elif marker.kind in {
            PageMarkerKind.DASHED_NUMBER,
            PageMarkerKind.PAGE_NUMBER,
            PageMarkerKind.NUMBER_OF_TOTAL,
            PageMarkerKind.PAGE_NUMBER_OF_TOTAL,
        }:
            decisions.append(
                PageMarkerDecision(
                    marker=marker,
                    action=PageMarkerAction.REMOVE,
                    reason="standard_page_footer",
                    confidence=0.95,
                )
            )
        elif marker.kind == PageMarkerKind.LETTER_NUMBER:
            if has_valid_seq or allow_letter_number:
                decisions.append(
                    PageMarkerDecision(
                        marker=marker,
                        action=PageMarkerAction.REMOVE,
                        reason="sequenced_letter_number_page",
                        confidence=0.85,
                    )
                )
            else:
                decisions.append(
                    PageMarkerDecision(
                        marker=marker,
                        action=PageMarkerAction.PRESERVE,
                        reason="ambiguous_letter_number",
                        confidence=0.7,
                    )
                )
        else:
            decisions.append(
                PageMarkerDecision(
                    marker=marker,
                    action=PageMarkerAction.PRESERVE,
                    reason="unclassified_marker",
                    confidence=0.5,
                )
            )

    boundaries = tuple(sorted({m.start for m in markers}))

    return PageMarkerAnalysis(
        markers=tuple(markers),
        decisions=tuple(decisions),
        page_boundaries=boundaries,
        representation=representation,
        source_text=document,
    )


def strip_page_markers(
    document: str,
    analysis: PageMarkerAnalysis | None = None,
) -> str:
    """Remove or normalize page markers according to classified decisions."""
    if not document:
        return ""

    if analysis is None or analysis.source_text != document:
        analysis = analyze_page_markers(document)

    # Collect removable spans in reverse order to preserve string indexing
    removable: list[tuple[int, int, str]] = []
    for decision in analysis.decisions:
        if decision.action in {PageMarkerAction.REMOVE, PageMarkerAction.NORMALIZE}:
            m = decision.marker
            start, end = m.start, m.end
            # If marker spans a full line, consume trailing newline if present
            if (
                (
                    start > 0
                    and document[start - 1] == "\n"
                    and end < len(document)
                    and document[end] == "\n"
                )
                or start == 0
                and end < len(document)
                and document[end] == "\n"
                or (
                    end < len(document)
                    and document[end] == "\n"
                    and (start == 0 or document[start - 1] == "\n")
                )
            ):
                end += 1
            removable.append((start, end, m.kind))

    removable.sort(key=lambda item: item[0], reverse=True)

    result = list(document)
    for start, end, kind in removable:
        replacement = (
            "\n" if kind == PageMarkerKind.SGML and ("<" in document[start:end]) else ""
        )
        result[start:end] = list(replacement)

    return "".join(result)


# Fast line-level predicate built from the existing private patterns.
# LETTER_NUMBER is excluded because it is opt-in only and ambiguous outside full-doc context.
_PAGE_MARKER_LINE_PATTERNS = (
    _RE_PAGE_NUMBER_OF_TOTAL,
    _RE_NUMBER_OF_TOTAL,
    _RE_PAGE_NUMBER,
    _RE_DASHED_NUMBER,
    _RE_SGML_LINE,
)


def is_page_marker_line(line: str) -> bool:
    """Return True if *line* (stripped) is a standalone page-break marker.

    Uses only the line-oriented patterns (not the inline SGML pattern or the
    opt-in LETTER_NUMBER pattern) so it is safe to call on individual lines
    without full-document context.
    """
    stripped = line.strip()
    if not stripped:
        return False
    return any(pat.match(stripped) for pat in _PAGE_MARKER_LINE_PATTERNS)


__all__ = [
    "PageMarker",
    "PageMarkerAction",
    "PageMarkerAnalysis",
    "PageMarkerDecision",
    "PageMarkerKind",
    "PageMarkerSpan",
    "analyze_page_markers",
    "find_page_markers",
    "is_page_marker_line",
    "strip_page_markers",
]
