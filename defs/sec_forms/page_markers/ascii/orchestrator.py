"""ASCII/SGML page-marker orchestration and coordinate-safe cleanup."""

from __future__ import annotations

from typing import Any

from ..models import (
    PageCandidate,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerKind,
    PageMarkerSpan,
    PageMarkerTerminalState,
)
from ..sequence import heal_run, validate_group
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


def _valid_firm_sequence(markers: list[PageMarker]) -> bool:
    from collections import defaultdict

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
    by_namespace: dict[str, list[PageCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_namespace[candidate.namespace].append(candidate)
    for ns_candidates in by_namespace.values():
        ns_candidates.sort(key=lambda item: (item.start_line, item.start))
        if validate_group(ns_candidates, strategy="firm") is None:
            return False
    return True


def _decision_for_marker(
    marker: PageMarker,
    *,
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
    if marker.kind == PageMarkerKind.LETTER_NUMBER and not valid_firm_sequence:
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
    allow_letter_number: bool = True,
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

    # The ASCII orchestrator never sees HTML: the package facade owns
    # representation dispatch. Fail loudly rather than scanning raw markup.
    if representation.casefold() == "html":
        raise ValueError(
            "ascii analyze_page_markers does not accept representation='html'; "
            "use defs.sec_forms.page_markers.orchestrator"
        )

    context = context or {}
    allow_table_furniture = bool(context.get("allow_table_furniture", False))
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
    anchored_markers, anchored_runs, anchored_accepted, anchored_rejections = (
        promote_groups(anchored_candidates, anchored=True)
        if anchor_lines
        else ([], [], [], ())
    )
    fallback_candidates = all_candidates(
        document,
        occupied_lines,
        allow_letter_number=allow_letter_number,
        excluded_lines=toc_exclusions,
    )
    fallback_markers, fallback_runs, fallback_accepted, fallback_rejections = (
        promote_groups(fallback_candidates, anchored=False)
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
            valid_firm_sequence=valid_firm_sequence,
        )
        for marker in markers
    ]

    runs = (*anchored_runs, *fallback_runs)
    # Cross-run context for healing: anchored runs rank above anchorless runs,
    # so anchorless runs never infer values the anchored runs already observed.
    # Promotion pools span both scans so anchorless discoveries can fill gaps.
    stronger_values: dict[str, set[int]] = {}
    candidate_pool: dict[tuple[str, Any], list[PageCandidate]] = {}
    for candidate in (*anchored_candidates, *fallback_candidates):
        candidate_pool.setdefault((candidate.namespace, candidate.family), []).append(
            candidate
        )
    firm_breaks = {
        marker.start_line
        for marker in markers
        if marker.kind in {PageMarkerKind.SGML, PageMarkerKind.BOUNDARY}
    }
    inferred = tuple(
        item
        for run in runs
        for item in heal_run(
            run,
            candidate_pool.get((run.namespace, run.family), ()),
            stronger_values=stronger_values.get(run.namespace, frozenset()),
            page_break_lines=firm_breaks or None,
        )[1]
    )
    for run in runs:
        stronger_values.setdefault(run.namespace, set()).update(
            candidate.value for candidate in run.candidates
        )
    # Prefer structural page breaks when available. Numeric labels can sit
    # before a firm break, while repeating furniture can sit after it; using
    # both would inflate the anchor denominator and understate presence.
    label_anchors = [marker for marker in markers if marker.page_number is not None]
    break_anchors = [
        marker
        for marker in markers
        if marker.kind in {PageMarkerKind.SGML, PageMarkerKind.BOUNDARY}
        and marker.start_line is not None
    ]
    combined_anchors = break_anchors if len(break_anchors) >= 3 else label_anchors
    header_anchor_lines = [
        marker.start_line
        for marker in (break_anchors if len(break_anchors) >= 3 else label_anchors)
        if marker.start_line is not None
    ]
    footer_anchor_lines = [
        marker.start_line
        for marker in (label_anchors if len(label_anchors) >= 3 else break_anchors)
        if marker.start_line is not None
    ]
    templates, presentation_markers, presentation_decisions = analyze_repeating_headers(
        document,
        combined_anchors,
        toc_lines=toc_exclusions,
        allow_table_furniture=allow_table_furniture,
        boundary_lines={
            line
            for marker in markers
            for line in range(marker.start_line or 0, (marker.end_line or 0) + 1)
        },
        header_anchors=header_anchor_lines,
        footer_anchors=footer_anchor_lines,
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
        rejection_diagnostics=(*anchored_rejections, *fallback_rejections),
    )


def find_page_markers(
    text: str, *, allow_letter_number: bool = True
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


__all__ = [
    "RE_PAGE_SUFFIX",
    "analyze_page_markers",
    "classify_candidate",
    "find_page_markers",
    "is_page_marker_line",
    "roman_to_int",
]
