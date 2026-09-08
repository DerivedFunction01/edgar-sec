"""Coordinate-safe application of validated ASCII page-marker decisions."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from ..artifacts import (
    note_template,
    render_page_artifact,
    token_kind_for,
)
from ..models import (
    PageArtifactPolicy,
    PageBreakArtifact,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerKind,
)
from .orchestrator import analyze_page_markers


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


def _marker_kind_for_source(source: str) -> str:
    if source == "repeating_header":
        return PageMarkerKind.REPEATING_HEADER
    if source == "repeating_footer":
        return PageMarkerKind.REPEATING_FOOTER
    return PageMarkerKind.BOUNDARY


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


__all__ = [
    "apply_page_markers",
    "strip_page_markers",
]
