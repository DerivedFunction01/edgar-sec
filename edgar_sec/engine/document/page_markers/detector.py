"""Page-marker detection across representations.

The analysis is one pass with three stages, and the order is what makes the
conservative parts conservative:

1. **Firm markers** are recognized by pattern alone. They are removed without
   corroboration, because each is a shape that cannot mean anything else.
2. **Candidates** are scanned twice — anchored to the firm markers' lines, and
   again anchorless — and admitted only in groups that validate as a page-number
   run.
3. **Furniture** is then recovered around whichever anchors survived, because a
   repeated banner is evidence about page structure only once the structure
   itself is known.

Every rejection is recorded by name in `rejection_diagnostics`, so a document
that produced no markers says which of the gates refused it.

An `html` representation has no markers: markup is projected to a text frame
first (see :mod:`edgar_sec.engine.document.page_markers.policy`), and this
module is not the place that projection happens.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .candidates import all_candidates, firm_markers, promote_groups, toc_lines
from .models import (
    PAGE_MARKER_PATTERNS,
    RE_BOUNDARY_TOKEN,
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
from .templates import analyze_repeating_headers


def _valid_firm_namespaces(markers: list[PageMarker]) -> set[str]:
    """Return the namespaces in which the firm markers form their own run.

    A namespaced firm label (`F-3`) is only trusted when the same namespace
    carries a validated sequence. Otherwise an exhibit reference that happens
    to look like `F-3` would be removed on the strength of its shape alone.
    """
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
    valid_namespaces: set[str] = set()
    for ns, ns_candidates in by_namespace.items():
        ns_candidates.sort(key=lambda item: (item.start_line, item.start))
        if validate_group(ns_candidates, strategy="firm") is not None:
            valid_namespaces.add(ns)
    return valid_namespaces


def _decision_for_marker(
    marker: PageMarker,
    *,
    valid_firm_namespaces: set[str],
) -> PageMarkerDecision:
    """Choose the action for one marker, stating the reason by shape."""
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
    if (
        marker.kind == PageMarkerKind.LETTER_NUMBER
        and marker.namespace not in valid_firm_namespaces
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
    """Return ``line:text`` for every candidate no run claimed."""
    accepted_spans = {(candidate.start, candidate.end) for candidate in accepted}
    return tuple(
        f"{candidate.start_line}:{candidate.text}"
        for candidate in candidates
        if (candidate.start, candidate.end) not in accepted_spans
    )


def analyze_page_markers(
    document: str,
    context: dict[str, Any] | None = None,
    *,
    representation: str = "ascii",
    allow_letter_number: bool = True,
) -> PageMarkerAnalysis:
    """Detect firm labels, validated candidates, and presentation evidence.

    ``context`` carries the caller's own evidence, never the caller's own
    conclusions: ``toc_lines`` names lines already known to be a table of
    contents, ``allow_table_furniture`` admits rendered table furniture, and
    ``source_identity`` is recorded on the result and on every emitted artifact.
    A missing ``toc_lines`` excludes nothing, because this module does not look
    for a table of contents itself.
    """

    if not document:
        return PageMarkerAnalysis(
            (),
            (),
            (),
            representation=representation,
            source_text=document,
            terminal_state=PageMarkerTerminalState.NO_VISIBLE_LABELS,
        )

    # This module never sees markup: representation dispatch belongs to
    # policy.py, which renders a text frame before analysis. Fail loudly
    # rather than scanning raw markup.
    if representation.casefold() == "html":
        raise ValueError(
            "analyze_page_markers does not accept representation='html'; "
            "project the document to a text frame first "
            "(edgar_sec.engine.document.page_markers.policy)"
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
    valid_firm_namespaces = _valid_firm_namespaces(firm)
    decisions = [
        _decision_for_marker(
            marker,
            valid_firm_namespaces=valid_firm_namespaces,
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
    header_markers = break_anchors if break_anchors else label_anchors
    footer_markers = label_anchors if label_anchors else break_anchors
    header_anchor_lines = [
        marker.start_line for marker in header_markers if marker.start_line is not None
    ]
    footer_anchor_lines = [
        marker.start_line for marker in footer_markers if marker.start_line is not None
    ]
    combined_anchors = list({*header_markers, *footer_markers})
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
    """Return accepted observed page-marker spans in source order.

    Recovering furniture is a separate concern with a separate pass, so the
    repeating header/footer spans are excluded here; a caller asking what page
    markers the document *states* does not get a block of body text back. The
    `page N of M` shape is reported as `number_of_total`, because that is what
    the shape is, and callers that care about the word `page` read the text.
    """

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
    """Return whether a line is a standalone firm marker or boundary token.

    The namespaced `F-3` form is excluded: it shares its shape with an exhibit
    reference, so it is not a marker line on the strength of the shape alone.
    """

    stripped = line.strip()
    if not stripped:
        return False
    return any(
        pattern.match(stripped)
        for kind, pattern in PAGE_MARKER_PATTERNS
        if kind != PageMarkerKind.LETTER_NUMBER
    ) or bool(RE_BOUNDARY_TOKEN.match(stripped))


__all__ = [
    "analyze_page_markers",
    "find_page_markers",
    "is_page_marker_line",
]
