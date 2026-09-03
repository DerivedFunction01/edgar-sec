"""ASCII/SGML page-marker orchestration and coordinate-safe cleanup."""

from __future__ import annotations

from typing import Any

from .candidates import (
    _PAGE_MARKER_PATTERNS,
    _RE_BOUNDARY,
    RE_PAGE_SUFFIX,
    all_candidates,
    classify_candidate,
    firm_markers,
    promote_groups,
    roman_to_int,
    toc_lines,
)
from .headers import analyze_repeating_headers
from .models import (
    PageCandidate,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerKind,
    PageMarkerSpan,
    PageMarkerTerminalState,
)
from .sequence import heal_run, validate_group


def _valid_firm_sequence(markers: list[PageMarker]) -> bool:
    candidates = [
        PageCandidate(
            marker.start,
            marker.end,
            marker.start_line or 0,
            marker.end_line or 0,
            marker.text,
            marker.family or marker.kind,
            marker.namespace,
            marker.page_number or 0,
        )
        for marker in markers
        if marker.page_number is not None
    ]
    return validate_group(candidates, strategy="firm") is not None


def _decision_for_marker(
    marker: PageMarker,
    *,
    allow_letter_number: bool,
    valid_firm_sequence: bool,
) -> PageMarkerDecision:
    if marker.kind == PageMarkerKind.BOUNDARY:
        return PageMarkerDecision(
            marker,
            PageMarkerAction.NORMALIZE,
            "boundary_only_marker",
            0.9,
            marker.evidence,
        )
    if marker.kind == PageMarkerKind.SGML:
        return PageMarkerDecision(
            marker, PageMarkerAction.REMOVE, "sgml_page_tag", 1.0, marker.evidence
        )
    if marker.kind == PageMarkerKind.LETTER_NUMBER and not (
        allow_letter_number or valid_firm_sequence
    ):
        return PageMarkerDecision(
            marker,
            PageMarkerAction.PRESERVE,
            "ambiguous_letter_number",
            0.7,
            marker.evidence,
        )
    if marker.family in {
        PageMarkerKind.APPENDIX_ROMAN,
        PageMarkerKind.BARE_NUMBER,
        PageMarkerKind.ROMAN_NUMBER,
        PageMarkerKind.PIPE_NUMBER,
        PageMarkerKind.PAREN_NUMBER,
        PageMarkerKind.DOTTED_NUMBER,
        PageMarkerKind.NUMBER_FIRST,
        PageMarkerKind.TRAILING_NUMBER,
        PageMarkerKind.INLINE_PAGE_NUMBER,
    }:
        return PageMarkerDecision(
            marker,
            PageMarkerAction.REMOVE,
            "validated_page_sequence",
            marker.confidence,
            marker.evidence,
        )
    return PageMarkerDecision(
        marker,
        PageMarkerAction.REMOVE,
        "standard_page_footer",
        0.95,
        marker.evidence,
    )


def _unresolved(
    candidates: list[PageCandidate], accepted: set[PageCandidate]
) -> tuple[str, ...]:
    return tuple(
        f"{candidate.start_line}:{candidate.text}"
        for candidate in candidates
        if candidate not in accepted
    )


def analyze_page_markers(
    document: str,
    context: dict[str, Any] | None = None,
    *,
    representation: str = "ascii",
    allow_letter_number: bool = False,
) -> PageMarkerAnalysis:
    """Detect firm labels, validated candidates, and presentation evidence."""

    if not document:
        return PageMarkerAnalysis(
            (),
            (),
            (),
            representation=representation,
            source_text=document,
            terminal_state=PageMarkerTerminalState.NO_VISIBLE_LABELS,
        )

    context = context or {}
    firm, _occupied_spans, occupied_lines = firm_markers(
        document, representation, allow_letter_number
    )
    toc_exclusions = set(context.get("toc_lines", ())) or toc_lines(document)
    anchor_lines = {
        line
        for marker in firm
        for line in range(marker.start_line or 0, (marker.end_line or 0) + 1)
    }

    anchored_candidates = all_candidates(
        document,
        occupied_lines,
        anchors=anchor_lines or None,
        allow_letter_number=allow_letter_number,
        excluded_lines=toc_exclusions,
    )
    anchored_markers, anchored_runs, anchored_accepted = (
        promote_groups(anchored_candidates, anchored=True)
        if anchor_lines
        else ([], [], [])
    )
    fallback_candidates = all_candidates(
        document,
        occupied_lines,
        allow_letter_number=allow_letter_number,
        excluded_lines=toc_exclusions,
    )
    fallback_markers, fallback_runs, fallback_accepted = promote_groups(
        fallback_candidates, anchored=False
    )

    markers = list(firm)
    seen_spans = {(marker.start, marker.end) for marker in markers}
    for marker in [*anchored_markers, *fallback_markers]:
        if (marker.start, marker.end) not in seen_spans:
            markers.append(marker)
            seen_spans.add((marker.start, marker.end))
    markers.sort(key=lambda marker: (marker.start, marker.end))
    valid_firm_sequence = _valid_firm_sequence(firm)
    decisions = [
        _decision_for_marker(
            marker,
            allow_letter_number=allow_letter_number,
            valid_firm_sequence=valid_firm_sequence,
        )
        for marker in markers
    ]

    runs = (*anchored_runs, *fallback_runs)
    inferred = tuple(item for run in runs for item in heal_run(run, run.candidates)[1])
    # SGML tags delimit pages, but are not sufficient evidence to remove
    # nearby presentation prose.
    label_anchors = [marker for marker in markers if marker.page_number is not None]
    templates, presentation_markers, presentation_decisions = analyze_repeating_headers(
        document, label_anchors, toc_lines=toc_exclusions
    )
    for marker, decision in zip(presentation_markers, presentation_decisions):
        if (marker.start, marker.end) not in seen_spans:
            markers.append(marker)
            decisions.append(decision)
    markers.sort(key=lambda marker: (marker.start, marker.end))
    decisions.sort(key=lambda item: (item.marker.start, item.marker.end))
    for marker in markers:
        occupied_lines.update(range(marker.start_line or 0, (marker.end_line or 0) + 1))

    accepted = {*anchored_accepted, *fallback_accepted}
    unresolved = _unresolved(
        anchored_candidates + fallback_candidates,
        accepted,
    )
    terminal = PageMarkerTerminalState.NONE
    if not any(marker.page_number is not None for marker in markers):
        terminal = PageMarkerTerminalState.NO_VISIBLE_LABELS
    elif unresolved:
        terminal = PageMarkerTerminalState.UNRESOLVED

    return PageMarkerAnalysis(
        markers=tuple(markers),
        decisions=tuple(decisions),
        page_boundaries=tuple(
            sorted(
                {
                    marker.start
                    for marker in markers
                    if marker.kind
                    not in {
                        PageMarkerKind.REPEATING_HEADER,
                        PageMarkerKind.REPEATING_FOOTER,
                    }
                }
            )
        ),
        representation=representation,
        source_text=document,
        source_identity=str(context.get("source_identity", "")),
        occupied_lines=tuple(sorted(occupied_lines)),
        page_number_runs=runs,
        header_footer_templates=templates,
        inferred_boundaries=inferred,
        unresolved=unresolved,
        terminal_state=terminal,
    )


def find_page_markers(
    text: str, *, allow_letter_number: bool = False
) -> tuple[PageMarkerSpan, ...]:
    """Return accepted observed page-marker spans in source order."""

    analysis = analyze_page_markers(
        text, allow_letter_number=allow_letter_number, representation="ascii"
    )
    return tuple(
        PageMarkerSpan(
            marker.start,
            marker.end,
            marker.text,
            (
                PageMarkerKind.NUMBER_OF_TOTAL
                if marker.kind == PageMarkerKind.PAGE_NUMBER_OF_TOTAL
                else marker.kind
            ),
            marker.page_number,
            marker.page_count,
        )
        for marker in analysis.markers
        if marker.kind
        not in {
            PageMarkerKind.REPEATING_HEADER,
            PageMarkerKind.REPEATING_FOOTER,
        }
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


def strip_page_markers(
    document: str, analysis: PageMarkerAnalysis | None = None
) -> str:
    """Apply only validated REMOVE/NORMALIZE decisions in the same source frame."""

    if not document:
        return ""
    if analysis is None or analysis.source_text != document:
        analysis = analyze_page_markers(document)
    removals: list[tuple[int, int]] = []
    for decision in analysis.decisions:
        if decision.action not in {
            PageMarkerAction.REMOVE,
            PageMarkerAction.NORMALIZE,
        }:
            continue
        marker = decision.marker
        if marker.coordinate_frame != "text":
            continue
        end = marker.end
        if (marker.start == 0 or document[marker.start - 1] == "\n") and (
            end >= len(document) or document[end] == "\n"
        ):
            end += int(end < len(document))
        removals.append((marker.start, end))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(removals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    result = document
    for start, end in reversed(merged):
        result = result[:start] + result[end:]
    return result


__all__ = [
    "RE_PAGE_SUFFIX",
    "analyze_page_markers",
    "classify_candidate",
    "find_page_markers",
    "is_page_marker_line",
    "roman_to_int",
    "strip_page_markers",
]
