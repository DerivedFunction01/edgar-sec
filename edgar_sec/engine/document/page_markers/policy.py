"""Applying the declared page-marker policy to a text frame.
Removal is coordinate-safe: a whole-line span takes its trailing newline, a span over a compact
`<TABLE>` widens to the whole table, a mid-sentence removal joins with a space.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Any

from edgar_sec.engine.document.html.breaks import render_html_to_break_text
from edgar_sec.foundation.text.healing import NEGATIVE_BOUNDARY_RE
from edgar_sec.foundation.text.patterns import RE_TERMINAL_BOUNDARY

from .artifacts import note_template, render_page_artifact, token_kind_for
from .detector import analyze_page_markers
from .models import (
    PageArtifactPolicy,
    PageBreakArtifact,
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerKind,
)

_TAGGED_TABLE = re.compile(r"<TABLE\b.*?</TABLE\s*>", re.IGNORECASE | re.DOTALL)

#: Widening onto a data table would delete document content; repeating furniture is a few lines tall.
_MAX_COMPACT_TABLE_LINES = 12

#: How far either side of a removal is read to decide whether it landed inside a sentence.
_BOUNDARY_WINDOW = 2000


def _find_compact_table_ranges(document: str) -> list[tuple[int, int]]:
    """Scan document once for compact rendered tables that can be atomic page furniture."""
    if "<table" not in document.lower():
        return []
    ranges: list[tuple[int, int]] = []
    for match in _TAGGED_TABLE.finditer(document):
        if match.group(0).count("\n") <= _MAX_COMPACT_TABLE_LINES:
            ranges.append((match.start(), match.end()))
    return ranges


def _expand_table_range(
    document: str,
    start: int,
    end: int,
    table_ranges: list[tuple[int, int]] | None = None,
) -> tuple[int, int]:
    """Make a page-furniture range atomic when it touches a tagged table.
    A marker covering only the wrapper or only the body strands the counterpart tag. Only compact tables qualify.
    """
    if table_ranges is None:
        table_ranges = _find_compact_table_ranges(document)
    for t_start, t_end in table_ranges:
        if t_start < end and t_end > start:
            return t_start, t_end
    return start, end


def _removal_range(
    document: str, start: int, end: int, table_ranges: list[tuple[int, int]]
) -> tuple[int, int]:
    """Widen one marker's span to the range a removal may actually cut."""
    if (start == 0 or document[start - 1] == "\n") and (
        end >= len(document) or document[end] == "\n"
    ):
        end += int(end < len(document))
    return _expand_table_range(document, start, end, table_ranges=table_ranges)


def _artifact_for_marker(marker: PageMarker, source_identity: str) -> PageBreakArtifact:
    """Build the provenance record for one validated removal."""
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
    """Return the marker kind a recorded artifact source came from."""
    if source == "repeating_header":
        return PageMarkerKind.REPEATING_HEADER
    if source == "repeating_footer":
        return PageMarkerKind.REPEATING_FOOTER
    return PageMarkerKind.BOUNDARY


def _needs_join(preceding: str, following: str) -> bool:
    """Return whether removing a span here would concatenate two sentence halves.
    The span is only owed a joining space when the text before it did not end a sentence, the text after it starts lowercase, and that text does not open with a negative boundary phrase — "none of" and "not only" continue the sentence, so joining them is a concatenation and not a splice.
    """
    return bool(
        preceding
        and following
        and not RE_TERMINAL_BOUNDARY.search(preceding)
        and following[:1].islower()
        and not NEGATIVE_BOUNDARY_RE.search(following)
    )


def apply_page_markers(
    document: str,
    analysis: PageMarkerAnalysis | None = None,
    policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    *,
    first_id: int = 1,
) -> tuple[str, tuple[PageBreakArtifact, ...], dict[str, dict], int]:
    """Apply the declared rendering policy to validated ASCII decisions.
    An analysis whose ``source_text`` is not this document is discarded: its offsets belong to another frame.
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

    # Overlapping decisions merge into one range so artifact ids stay sequential.
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
        start, end = _removal_range(document, marker.start, marker.end, table_ranges)
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

        prec_window = document[max(0, start - _BOUNDARY_WINDOW) : start].rstrip()
        prec_exists = bool(prec_window) or bool(document[:start].strip())

        succ_window = ""
        for seg in segments:
            s = seg.lstrip()
            if s:
                succ_window = s[:_BOUNDARY_WINDOW]
                break
        succ_exists = bool(succ_window)

        if _needs_join(prec_window, succ_window) and prec_exists and succ_exists:
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


def apply_text_policy(
    text: str,
    analysis: PageMarkerAnalysis | None = None,
    policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    *,
    first_id: int = 1,
) -> tuple[
    str, PageMarkerAnalysis, tuple[PageBreakArtifact, ...], dict[str, dict], int
]:
    """Apply the policy to text-frame decisions via the ASCII detector.
    The returned analysis stays in the ASCII text coordinate frame.
    """

    if analysis is None:
        analysis = analyze_page_markers(text, representation="ascii")
    text, artifacts, templates, next_id = apply_page_markers(
        text, analysis, policy, first_id=first_id
    )
    return text, analysis, artifacts, templates, next_id


def apply_fast_html_page_policy(
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
    """Render HTML to a text frame and apply page-marker decisions to it.
    Table furniture is admitted only here: a rendered ``<TABLE>`` is how a filing prints a banner.
    """

    normalized = render_html_to_break_text(html)
    text = str(normalized)
    analysis_context = dict(context or {})
    analysis_context["allow_table_furniture"] = True
    if analysis is None or analysis.representation == "html":
        analysis = analyze_page_markers(
            text,
            analysis_context,
            representation="ascii",
            allow_letter_number=allow_letter_number,
        )
    result_text, artifacts, templates, next_id = apply_page_markers(
        text,
        analysis,
        policy,
        first_id=first_id,
    )
    return (
        result_text,
        analysis,
        artifacts,
        templates,
        next_id,
        normalized.table_geometries,
    )


def apply_html_policy(
    html: str,
    analysis: PageMarkerAnalysis | None = None,
    policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    *,
    first_id: int = 1,
    allow_letter_number: bool = True,
) -> tuple[
    str,
    PageMarkerAnalysis,
    tuple[PageBreakArtifact, ...],
    dict[str, dict],
    int,
    tuple,
]:
    """Apply page policy to HTML input using the string-first fast path."""

    return apply_fast_html_page_policy(
        html,
        analysis,
        policy,
        first_id=first_id,
        allow_letter_number=allow_letter_number,
    )


__all__ = [
    "apply_fast_html_page_policy",
    "apply_html_policy",
    "apply_page_markers",
    "apply_text_policy",
]
