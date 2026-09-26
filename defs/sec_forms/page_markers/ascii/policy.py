"""Coordinate-safe application of validated ASCII page-marker decisions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from defs.text.healing.lines import NEGATIVE_BOUNDARY_RE
from defs.text.structure.patterns import RE_TERMINAL_BOUNDARY

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

_TERMINAL_PUNCT = RE_TERMINAL_BOUNDARY
_TAGGED_TABLE = re.compile(r"<TABLE\b.*?</TABLE\s*>", re.IGNORECASE | re.DOTALL)


def _find_compact_table_ranges(document: str) -> list[tuple[int, int]]:
    """Scan document once for compact rendered tables that can be atomic page furniture."""
    if "<table" not in document.lower():
        return []
    ranges: list[tuple[int, int]] = []
    for match in _TAGGED_TABLE.finditer(document):
        if match.group(0).count("\n") <= 12:
            ranges.append((match.start(), match.end()))
    return ranges


def _expand_table_range(
    document: str,
    start: int,
    end: int,
    table_ranges: list[tuple[int, int]] | None = None,
) -> tuple[int, int]:
    """Make a page-furniture range atomic when it touches a tagged table.

    HTML page conversion emits canonical ``<TABLE>`` wrappers around rendered
    furniture. A marker can cover only the wrapper or only the body, which
    would leave the counterpart tag behind. Expand such a range to the entire
    table before applying removals. Only compact tables qualify: repeating
    page furniture is a few lines tall, while widening onto a large data
    table would delete document content.
    """
    if table_ranges is None:
        table_ranges = _find_compact_table_ranges(document)
    for t_start, t_end in table_ranges:
        if t_start < end and t_end > start:
            return t_start, t_end
    return start, end


def strip_page_markers(
    document: str, analysis: PageMarkerAnalysis | None = None
) -> str:
    """Apply only validated REMOVE/NORMALIZE decisions in the same source frame."""

    if not document:
        return ""
    if analysis is None or analysis.source_text != document:
        analysis = analyze_page_markers(document)
    table_ranges = _find_compact_table_ranges(document)
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
        start, end = _expand_table_range(
            document, marker.start, end, table_ranges=table_ranges
        )
        removals.append((start, end))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(removals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    result = document
    for start, end in reversed(merged):
        prec = result[:start].rstrip()
        succ = result[end:].lstrip()
        if (
            prec
            and succ
            and not _TERMINAL_PUNCT.search(prec)
            and succ[:1].islower()
            and not NEGATIVE_BOUNDARY_RE.search(succ)
        ):
            result = prec + " " + succ
        else:
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
    table_ranges = _find_compact_table_ranges(document)
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
        start, end = _expand_table_range(
            document, marker.start, end, table_ranges=table_ranges
        )
        artifact = _note(marker, _artifact_for_marker(marker, source_identity))
        if ranges and start <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], end)
            ranges[-1][2].append(artifact)
        else:
            ranges.append([start, end, [artifact]])

    next_id = first_id
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

    if not prepared:
        return document, (), templates, next_id

    assigned = [member for _, _, _, members in prepared for member in members]
    artifacts.extend(assigned)

    if policy == PageArtifactPolicy.ANNOTATE:
        chunks = []
        last_pos = 0
        for start, end, token, _ in prepared:
            chunks.append(document[last_pos:start])
            newline = "\n" if document[end - 1 : end] == "\n" else ""
            chunks.append(token + newline)
            last_pos = end
        chunks.append(document[last_pos:])
        result = "".join(chunks)

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
        if insertions:
            for line_index, token, artifact in reversed(insertions):
                lines.insert(line_index, token)
                artifacts.append(artifact)
            result = "\n".join(lines)
            if document.endswith("\n") and not result.endswith("\n"):
                result += "\n"
        return result, tuple(artifacts), templates, next_id

    # STRIP policy: linear reverse segment assembly with boundary healing
    segments = [document[prepared[-1][1] :]]
    for i in range(len(prepared) - 1, -1, -1):
        start, end, _, _ = prepared[i]
        prev_end = prepared[i - 1][1] if i > 0 else 0
        intervening = document[prev_end:start]

        prec_window = document[max(0, start - 2000) : start].rstrip()
        prec_exists = bool(prec_window) or bool(document[:start].strip())

        succ_window = ""
        for seg in segments:
            s = seg.lstrip()
            if s:
                succ_window = s[:2000]
                break
        succ_exists = bool(succ_window)

        if (
            prec_exists
            and succ_exists
            and not _TERMINAL_PUNCT.search(prec_window)
            and succ_window[:1].islower()
            and not NEGATIVE_BOUNDARY_RE.search(succ_window)
        ):
            for idx in range(len(segments)):
                if segments[idx].strip():
                    segments[idx] = segments[idx].lstrip()
                    break
                segments[idx] = ""
            intervening = intervening.rstrip() + " "
            segments.insert(0, intervening)
        else:
            segments.insert(0, intervening)

    return "".join(segments), tuple(artifacts), templates, next_id


__all__ = [
    "apply_page_markers",
    "strip_page_markers",
]
