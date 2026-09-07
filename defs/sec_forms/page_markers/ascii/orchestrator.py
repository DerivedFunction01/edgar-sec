"""ASCII/SGML page-marker orchestration and coordinate-safe cleanup."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from ..artifacts import (
    note_template,
    render_page_artifact,
    token_kind_for,
)
from ..models import (
    PageArtifactPolicy,
    PageBreakArtifact,
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


def _artifact_for_marker(marker: PageMarker, source_identity: str) -> PageBreakArtifact:
    if marker.kind == PageMarkerKind.REPEATING_HEADER:
        source = "repeating_header"
    elif marker.kind == PageMarkerKind.REPEATING_FOOTER:
        source = "repeating_footer"
    elif marker.kind == PageMarkerKind.SGML:
        source = "sgml-page-tag"
    elif marker.kind == PageMarkerKind.BOUNDARY:
        source = "boundary-marker"
    else:
        source = marker.kind
    return PageBreakArtifact(
        page_number=marker.page_number,
        namespace=marker.namespace or None,
        source=source,
        coordinate_frame=marker.coordinate_frame,
        source_identity=source_identity,
        start=marker.start,
        end=marker.end,
        start_line=marker.start_line,
        end_line=marker.end_line,
        removable=True,
    )


def apply_page_markers(
    document: str,
    analysis: PageMarkerAnalysis | None = None,
    policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    *,
    first_id: int = 1,
) -> tuple[str, tuple[PageBreakArtifact, ...], dict[str, dict], int]:
    """Apply the declared rendering policy to validated ASCII decisions.

    Returns the rendered text, recorded artifacts, deduplicated template
    entries, and the next free artifact id. ``strip`` removes validated
    furniture and records provenance; ``annotate`` replaces each validated
    span with a canonical token line; ``preserve`` leaves the source intact.
    Metadata-only inferred boundaries emit artifacts only in ``annotate``
    mode, at their line coordinate, and are never removable.
    """

    if not document:
        return "", (), {}, first_id
    if policy == PageArtifactPolicy.PRESERVE:
        return document, (), {}, first_id
    if analysis is None or analysis.source_text != document:
        analysis = analyze_page_markers(document)
    source_identity = (
        analysis.source_identity or hashlib.sha256(document.encode("utf-8")).hexdigest()
    )
    templates: dict[str, dict] = {}
    artifacts: list[PageBreakArtifact] = []

    def _note(marker: PageMarker, artifact: PageBreakArtifact) -> PageBreakArtifact:
        if marker.kind not in {
            PageMarkerKind.REPEATING_HEADER,
            PageMarkerKind.REPEATING_FOOTER,
        }:
            return artifact
        template_id = note_template(
            templates,
            marker.kind,
            marker.text,
            page_number=marker.page_number,
        )
        if not template_id:
            return artifact
        return replace(artifact, template_id=template_id)

    # Replacement ranges in document order; overlapping decisions merge into
    # one range carrying every decision so ids stay sequential and stable.
    ranges: list[list] = []  # [start, end, [artifact, ...]]
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
        artifact = _note(marker, _artifact_for_marker(marker, source_identity))
        if ranges and marker.start <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], end)
            ranges[-1][2].append(artifact)
        else:
            ranges.append([marker.start, end, [artifact]])

    result = document
    assigned: list[PageBreakArtifact] = []
    next_id = first_id
    # Ids are assigned in document order; replacement runs back to front so
    # earlier offsets stay valid while later spans are rewritten.
    prepared: list[tuple[int, int, str, list[PageBreakArtifact]]] = []
    for start, end, members in ranges:
        kinds = {
            token_kind_for(_marker_kind_for_source(artifact.source))
            for artifact in members
        }
        token_kind = "PAGE_BREAK" if "PAGE_BREAK" in kinds else min(kinds)
        prepared.append(
            (start, end, render_page_artifact(token_kind, next_id), members)
        )
        next_id += 1
    for start, end, token, members in reversed(prepared):
        if policy == PageArtifactPolicy.ANNOTATE:
            newline = "\n" if result[end - 1 : end] == "\n" else ""
            result = result[:start] + token + newline + result[end:]
        else:
            result = result[:start] + result[end:]
        assigned.extend(members)
    assigned.reverse()
    artifacts.extend(assigned)

    if policy == PageArtifactPolicy.ANNOTATE:
        lines = result.splitlines()
        line_offsets: list[int] = []
        offset = 0
        for line in lines:
            line_offsets.append(offset)
            offset += len(line) + 1
        insertions: list[tuple[int, str, PageBreakArtifact]] = []
        for boundary in analysis.inferred_boundaries:
            line_index = int(boundary.line)
            if not 0 <= line_index < len(lines):
                continue
            artifact = PageBreakArtifact(
                page_number=boundary.page_number,
                namespace=boundary.namespace,
                source="inferred-line",
                coordinate_frame=analysis.coordinate_frame,
                source_identity=source_identity,
                start=line_offsets[line_index],
                end=line_offsets[line_index],
                start_line=line_index,
                end_line=line_index,
                removable=False,
            )
            insertions.append(
                (line_index, render_page_artifact("PAGE_BREAK", next_id), artifact)
            )
            next_id += 1
        for line_index, token, artifact in reversed(insertions):
            result = (
                result[: line_offsets[line_index]]
                + token
                + "\n"
                + result[line_offsets[line_index] :]
            )
        artifacts.extend(artifact for _, _, artifact in insertions)

    return result, tuple(artifacts), templates, next_id


def _marker_kind_for_source(source: str) -> str:
    if source == "repeating_header":
        return PageMarkerKind.REPEATING_HEADER
    if source == "repeating_footer":
        return PageMarkerKind.REPEATING_FOOTER
    return PageMarkerKind.BOUNDARY


__all__ = [
    "RE_PAGE_SUFFIX",
    "analyze_page_markers",
    "apply_page_markers",
    "classify_candidate",
    "find_page_markers",
    "is_page_marker_line",
    "roman_to_int",
    "strip_page_markers",
]
