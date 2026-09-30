"""Bounded-window running header/footer and page marker detection."""

from __future__ import annotations

import bisect
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import ROMAN_NUMERAL_PATTERN, roman_to_int


class PageMarkerKind:
    """Names for supported page-marker and presentation shapes."""

    SGML = "sgml"
    DASHED_NUMBER = "dashed_number"
    PAGE_NUMBER = "page_number"
    NUMBER_OF_TOTAL = "number_of_total"
    PAGE_NUMBER_OF_TOTAL = "page_number_of_total"
    LETTER_NUMBER = "letter_number"
    APPENDIX_ROMAN = "appendix_roman"
    BARE_NUMBER = "bare_number"
    ROMAN_NUMBER = "roman_number"
    PIPE_NUMBER = "pipe_number"
    PAREN_NUMBER = "paren_number"
    DOTTED_NUMBER = "dotted_number"
    NUMBER_FIRST = "number_first"
    TRAILING_NUMBER = "trailing_number"
    INLINE_PAGE_NUMBER = "inline_page_number"
    BOUNDARY = "boundary"
    REPEATING_HEADER = "repeating_header"
    REPEATING_FOOTER = "repeating_footer"


class PageMarkerAction(StrEnum):
    """Decision actions for page-marker post-processing."""

    REMOVE = "remove"
    NORMALIZE = "normalize"
    PRESERVE = "preserve"


class PageMarkerTerminalState(StrEnum):
    """Terminal outcomes for page-marker analysis."""

    NONE = "none"
    NO_VISIBLE_LABELS = "no_visible_labels"
    UNRESOLVED = "unresolved"


class PageArtifactPolicy(StrEnum):
    """Rendering policy for validated page furniture."""

    STRIP = "strip"
    ANNOTATE = "annotate"
    PRESERVE = "preserve"


@dataclass(frozen=True, slots=True)
class PageMarker:
    """One recognized page-furniture occurrence."""

    start: int
    end: int
    text: str
    kind: str
    page_number: int | None = None
    page_count: int | None = None
    confidence: float = 1.0
    family: str = ""
    evidence: tuple[str, ...] = ()
    start_line: int | None = None
    end_line: int | None = None
    namespace: str = ""
    coordinate_frame: str = "text"


@dataclass(frozen=True, slots=True)
class PageCandidate:
    """A candidate label found during contextual scan."""

    start: int
    end: int
    start_line: int
    end_line: int
    text: str
    family: str
    namespace: str
    value: int
    relative_position: int | None = None
    leading_column: int = 0
    template: str = ""
    exclusion: str = ""
    coordinate_frame: str = "text"


@dataclass(frozen=True, slots=True)
class PageNumberRun:
    """One independently validated observed page-number run."""

    family: str
    namespace: str
    candidates: tuple[PageCandidate, ...]
    monotone_fraction: float
    gap_mean: float
    gap_median: float
    alignment_fraction: float
    source_start_line: int
    source_end_line: int
    strategy: str


@dataclass(frozen=True, slots=True)
class InferredBoundary:
    """Metadata-only page boundary with no removable source span."""

    line: float
    page_number: int | None
    namespace: str
    reason: str


@dataclass(frozen=True, slots=True)
class PageMarkerDecision:
    """Decision action for one marker."""

    marker: PageMarker
    action: PageMarkerAction
    reason: str
    confidence: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PageBreakArtifact:
    """Emitted page-break artifact metadata."""

    artifact_id: int
    kind: str
    template_id: str
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PageMarkerAnalysis:
    """Aggregated results of page-marker detection and validation."""

    markers: tuple[PageMarker, ...]
    decisions: tuple[PageMarkerDecision, ...]
    unresolved_candidates: tuple[str, ...] = ()
    rejection_diagnostics: tuple[str, ...] = ()
    page_boundaries: tuple[int, ...] = ()
    page_number_runs: tuple[PageNumberRun, ...] = ()
    occupied_lines: tuple[int, ...] = ()
    representation: str = "ascii"
    source_text: str = ""
    terminal_state: PageMarkerTerminalState = PageMarkerTerminalState.NONE


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
_RE_PAGE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_RE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_RE_PAGE_NUMBER = re.compile(
    r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]*$", re.IGNORECASE
)
_RE_DASHED_NUMBER = re.compile(r"(?im)^[ \t]*-[ \t]*(?P<page>\d+)[ \t]*-[ \t]*$")
_RE_LETTER_NUMBER = re.compile(
    r"(?im)^\s*(?:page\s+)?(?P<prefix>[A-Z])\s*[-–—]\s*(?P<page>\d+)\s*[-–—]?\s*$"
)
_RE_SGML_LINE = re.compile(
    r"(?im)^[ \t]*</?PAGE\b[^>]*>[ \t]*"
    r"(?P<page>(?:[A-Z](?:\s*[-–—]\s*\d+)?|\d+))?[ \t]*"
    r"(?:</?PAGE\b[^>]*>)?[ \t]*$"
)
_RE_SGML_INLINE = re.compile(r"(?i)</?PAGE\b[^>]*>")
_RE_BOUNDARY = re.compile(r"(?im)^[ \t]*(?:\(PAGE\)|\[PAGE\])[ \t]*$")

_PAGE_ARABIC = r"\d{1,4}"
_PAGE_ROMAN = ROMAN_NUMERAL_PATTERN
_PAGE_VALUE = rf"(?:{_PAGE_ARABIC}|{_PAGE_ROMAN})"
_WRAPPERS = build_alternation(["-", "–", "—", ".", "·", "•", "▪"], auto_escape=True)

_RE_DASH_LABEL = re.compile(
    rf"^(?=.*(?:{_WRAPPERS}))(?:{_WRAPPERS}|\s)+"
    rf"(?P<value>{_PAGE_VALUE})"
    rf"(?:{_WRAPPERS}|\s)+$",
    re.IGNORECASE,
)
_RE_PIPE_LABEL = re.compile(rf"^\|\s*(?P<value>{_PAGE_VALUE})\s*\|$", re.IGNORECASE)
_RE_PAREN_LABEL = re.compile(rf"^\(\s*(?P<value>{_PAGE_VALUE})\s*\)$", re.IGNORECASE)
_RE_DOTTED_LABEL = re.compile(rf"^(?P<value>{_PAGE_ARABIC})\.$")
_RE_BARE_ARABIC = re.compile(rf"^(?P<value>{_PAGE_ARABIC})$")
_RE_BARE_ROMAN = re.compile(rf"^(?P<value>{_PAGE_ROMAN})$", re.IGNORECASE)

_PAGE_MARKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (PageMarkerKind.PAGE_NUMBER_OF_TOTAL, _RE_PAGE_NUMBER_OF_TOTAL),
    (PageMarkerKind.NUMBER_OF_TOTAL, _RE_NUMBER_OF_TOTAL),
    (PageMarkerKind.PAGE_NUMBER, _RE_PAGE_NUMBER),
    (PageMarkerKind.DASHED_NUMBER, _RE_DASHED_NUMBER),
    (PageMarkerKind.LETTER_NUMBER, _RE_LETTER_NUMBER),
    (PageMarkerKind.SGML, _RE_SGML_LINE),
    (PageMarkerKind.SGML, _RE_SGML_INLINE),
)

_TAGGED_TABLE = re.compile(r"<TABLE\b.*?</TABLE\s*>", re.IGNORECASE | re.DOTALL)


def _line_offsets(lines: Sequence[str]) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1
    return offsets


def _line_for_offset(offsets: list[int], offset: int) -> int:
    return max(0, min(bisect.bisect_right(offsets, offset) - 1, len(offsets) - 1))


def _marker_lines(
    start: int, end: int, text: str, offsets: list[int]
) -> tuple[int, int]:
    value = text[start:end]
    first = start + len(value) - len(value.lstrip())
    return _line_for_offset(offsets, first), _line_for_offset(
        offsets, max(first, end - 1)
    )


def _find_firm_markers(text: str, allow_letter_number: bool = True) -> list[PageMarker]:
    offsets = _line_offsets(text.splitlines())
    occupied_starts: list[int] = []
    occupied_ends: list[int] = []
    markers: list[PageMarker] = []

    def _is_occupied(s: int, e: int) -> bool:
        idx = bisect.bisect_right(occupied_starts, s)
        if idx > 0 and occupied_ends[idx - 1] > s:
            return True
        return idx < len(occupied_starts) and occupied_starts[idx] < e

    def _add_occupied(s: int, e: int) -> None:
        idx = bisect.bisect_right(occupied_starts, s)
        occupied_starts.insert(idx, s)
        occupied_ends.insert(idx, e)

    for kind, pattern in _PAGE_MARKER_PATTERNS:
        if kind == PageMarkerKind.LETTER_NUMBER and not allow_letter_number:
            continue
        for match in pattern.finditer(text):
            start, end = match.span()
            if _is_occupied(start, end):
                continue
            _add_occupied(start, end)
            groups = match.groupdict()
            start_line, end_line = _marker_lines(start, end, text, offsets)
            page = groups.get("page")
            count = groups.get("count")

            page_num: int | None = None
            if page:
                clean_page = page.strip()
                if clean_page.isdigit():
                    page_num = int(clean_page)
                elif "-" in clean_page or "–" in clean_page or "—" in clean_page:
                    parts = re.split(r"[-–—]", clean_page)
                    if len(parts) >= 2 and parts[-1].strip().isdigit():
                        page_num = int(parts[-1].strip())
                else:
                    page_num = roman_to_int(clean_page)

            page_cnt = int(count) if count and count.isdigit() else None
            matched_text = match.group(0).strip()
            markers.append(
                PageMarker(
                    start=start,
                    end=end,
                    text=matched_text,
                    kind=kind,
                    page_number=page_num,
                    page_count=page_cnt,
                    confidence=1.0,
                    family=kind,
                    evidence=(kind,),
                    start_line=start_line,
                    end_line=end_line,
                )
            )

    markers.sort(key=lambda m: (m.start, m.end))
    return markers


def _find_repeating_headers(
    lines: list[str],
    line_offsets_list: list[int],
    firm_markers_list: list[PageMarker],
) -> list[PageMarker]:
    """Identify recurring header furniture near page boundaries."""
    page_break_lines: set[int] = set()
    for m in firm_markers_list:
        if m.start_line is not None:
            page_break_lines.add(m.start_line)

    candidate_counts: dict[str, list[int]] = defaultdict(list)
    for idx, line in enumerate(lines):
        clean = line.strip()
        if not clean or len(clean) < 3 or len(clean) > 120:
            continue
        if (
            "<table" in clean.lower()
            or "</table" in clean.lower()
            or "<page" in clean.lower()
            or "</page" in clean.lower()
        ):
            continue
        is_near_break = any(abs(idx - pb) <= 4 for pb in page_break_lines)
        if is_near_break:
            candidate_counts[clean].append(idx)

    repeated_markers: list[PageMarker] = []
    for text_clean, occurrences in candidate_counts.items():
        if len(occurrences) >= 3:
            for line_idx in occurrences:
                start_offset = line_offsets_list[line_idx]
                end_offset = start_offset + len(lines[line_idx])
                repeated_markers.append(
                    PageMarker(
                        start=start_offset,
                        end=end_offset,
                        text=text_clean,
                        kind=PageMarkerKind.REPEATING_HEADER,
                        confidence=0.9,
                        family=PageMarkerKind.REPEATING_HEADER,
                        evidence=(
                            "repeating_header",
                            f"occurrences:{len(occurrences)}",
                        ),
                        start_line=line_idx,
                        end_line=line_idx + 1,
                    )
                )

    repeated_markers.sort(key=lambda m: m.start)
    return repeated_markers


def analyze_page_markers(
    document: str,
    context: dict[str, Any] | None = None,
    *,
    representation: str = "ascii",
    allow_letter_number: bool = True,
) -> PageMarkerAnalysis:
    """Analyze page markers in the text representation frame."""
    if not document:
        return PageMarkerAnalysis(
            (),
            (),
            (),
            representation=representation,
            source_text=document,
            terminal_state=PageMarkerTerminalState.NO_VISIBLE_LABELS,
        )

    lines = document.splitlines()
    offsets = _line_offsets(lines)
    firm = _find_firm_markers(document, allow_letter_number=allow_letter_number)
    repeated = _find_repeating_headers(lines, offsets, firm)

    all_markers = sorted(firm + repeated, key=lambda m: (m.start, m.end))
    decisions: list[PageMarkerDecision] = []
    for marker in all_markers:
        action = PageMarkerAction.REMOVE
        reason = "standard_page_marker"
        if marker.kind == PageMarkerKind.SGML:
            reason = "sgml_page_tag"
        elif marker.kind == PageMarkerKind.REPEATING_HEADER:
            reason = "repeating_header_furniture"
        decisions.append(
            PageMarkerDecision(
                marker=marker,
                action=action,
                reason=reason,
                confidence=marker.confidence,
                evidence=marker.evidence,
            )
        )

    terminal_state = (
        PageMarkerTerminalState.NONE
        if all_markers
        else PageMarkerTerminalState.NO_VISIBLE_LABELS
    )
    page_boundaries = tuple(
        m.start_line for m in all_markers if m.start_line is not None
    )
    occupied_lines = tuple(
        line
        for m in all_markers
        if m.start_line is not None
        for line in range(m.start_line, m.end_line or (m.start_line + 1))
    )

    return PageMarkerAnalysis(
        markers=tuple(all_markers),
        decisions=tuple(decisions),
        unresolved_candidates=(),
        rejection_diagnostics=(),
        page_boundaries=page_boundaries,
        page_number_runs=(),
        occupied_lines=occupied_lines,
        representation=representation,
        source_text=document,
        terminal_state=terminal_state,
    )


def _find_compact_table_ranges(document: str) -> list[tuple[int, int]]:
    if "<table" not in document.lower():
        return []
    ranges: list[tuple[int, int]] = []
    for match in _TAGGED_TABLE.finditer(document):
        if match.group(0).count("\n") <= 12:
            ranges.append((match.start(), match.end()))
    return ranges


def _expand_table_range(
    start: int,
    end: int,
    table_ranges: list[tuple[int, int]],
) -> tuple[int, int]:
    for t_start, t_end in table_ranges:
        if t_start < end and t_end > start:
            return t_start, t_end
    return start, end


def strip_page_markers(
    document: str, analysis: PageMarkerAnalysis | None = None
) -> str:
    """Apply only validated REMOVE decisions in the same source frame."""
    if not document:
        return ""
    if analysis is None or analysis.source_text != document:
        analysis = analyze_page_markers(document)

    table_ranges = _find_compact_table_ranges(document)
    removals: list[tuple[int, int]] = []
    for decision in analysis.decisions:
        if decision.action != PageMarkerAction.REMOVE:
            continue
        marker = decision.marker
        end = marker.end
        if (marker.start == 0 or document[marker.start - 1] == "\n") and (
            end >= len(document) or document[end] == "\n"
        ):
            end += int(end < len(document))
        start, end = _expand_table_range(marker.start, end, table_ranges)
        removals.append((start, end))

    merged: list[tuple[int, int]] = []
    for start, end in sorted(removals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    pieces: list[str] = []
    cursor = 0
    for start, end in merged:
        pieces.append(document[cursor:start])
        cursor = end
    pieces.append(document[cursor:])
    return "".join(pieces)


def apply_text_policy(
    text: str,
    analysis: PageMarkerAnalysis | None = None,
    policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    *,
    first_id: int = 1,
    representation: str = "ascii",
) -> tuple[
    str, PageMarkerAnalysis, tuple[PageBreakArtifact, ...], dict[str, dict], int
]:
    """Apply policy to text-frame page markers."""
    if analysis is None:
        analysis = analyze_page_markers(text, representation=representation)

    if policy == PageArtifactPolicy.PRESERVE:
        return text, analysis, (), {}, first_id

    cleaned = strip_page_markers(text, analysis)
    artifacts: list[PageBreakArtifact] = [
        PageBreakArtifact(
            artifact_id=first_id + i,
            kind=d.marker.kind,
            template_id=d.reason,
            attributes={"text": d.marker.text},
        )
        for i, d in enumerate(analysis.decisions)
        if d.action == PageMarkerAction.REMOVE
    ]
    return cleaned, analysis, tuple(artifacts), {}, first_id + len(artifacts)


def apply_html_policy(
    html: str,
    analysis: PageMarkerAnalysis | None = None,
    policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    *,
    first_id: int = 1,
    context: dict[str, Any] | None = None,
    allow_letter_number: bool = True,
) -> tuple[
    str,
    PageMarkerAnalysis,
    tuple[PageBreakArtifact, ...],
    dict[str, dict],
    int,
    tuple,
]:
    """Render fast HTML text and apply page-marker decisions."""
    from edgar_sec.engine.document.html import normalize_html_document
    from edgar_sec.engine.document.html_breaks import (
        convert_sentinels_to_page_markers,
        insert_page_sentinels,
    )

    if not html:
        empty_analysis = PageMarkerAnalysis(
            (),
            (),
            (),
            representation="html",
            source_text="",
            terminal_state=PageMarkerTerminalState.NO_VISIBLE_LABELS,
        )
        return "", empty_analysis, (), {}, first_id, ()

    break_html = insert_page_sentinels(html)
    normalized = normalize_html_document(break_html)
    text = convert_sentinels_to_page_markers(str(normalized))

    if analysis is None or analysis.representation == "html":
        analysis = analyze_page_markers(
            text,
            context=context,
            representation="html",
            allow_letter_number=allow_letter_number,
        )

    if policy == PageArtifactPolicy.PRESERVE:
        return text, analysis, (), {}, first_id, normalized.table_geometries

    cleaned = strip_page_markers(text, analysis)
    artifacts: list[PageBreakArtifact] = [
        PageBreakArtifact(
            artifact_id=first_id + i,
            kind=d.marker.kind,
            template_id=d.reason,
            attributes={"text": d.marker.text},
        )
        for i, d in enumerate(analysis.decisions)
        if d.action == PageMarkerAction.REMOVE
    ]
    return (
        cleaned,
        analysis,
        tuple(artifacts),
        {},
        first_id + len(artifacts),
        normalized.table_geometries,
    )


def is_page_marker_line(line: str) -> bool:
    """Return whether a line is a standalone firm marker or boundary token."""
    stripped = line.strip()
    if not stripped:
        return False
    return any(
        pattern.match(stripped)
        for kind, pattern in _PAGE_MARKER_PATTERNS
        if kind != PageMarkerKind.LETTER_NUMBER
    ) or bool(_RE_BOUNDARY.match(stripped))


__all__ = [
    "InferredBoundary",
    "PageArtifactPolicy",
    "PageBreakArtifact",
    "PageCandidate",
    "PageMarker",
    "PageMarkerAction",
    "PageMarkerAnalysis",
    "PageMarkerDecision",
    "PageMarkerKind",
    "PageMarkerTerminalState",
    "PageNumberRun",
    "analyze_page_markers",
    "apply_html_policy",
    "apply_text_policy",
    "is_page_marker_line",
    "strip_page_markers",
]
