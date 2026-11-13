"""Per-filing successor extraction: normalize under the annotate policy
and assemble the context record kept per geometry.

Location is found by ordered sequential search of each geometry's
rendered lines in the annotated text frame; a geometry that cannot be
located is an issue on its record, never a silent drop.
"""

from __future__ import annotations

import difflib
import re
import time

from edgar_sec.engine.document.page_markers.models import PageArtifactPolicy
from edgar_sec.engine.forms.normalize import NormalizationResult, normalize_document
from edgar_sec.engine.tables.extraction.typed_rows import parse_caption_stack
from edgar_sec.engine.tables.patterns import SCALE_PATTERNS

_TOKEN_RE = re.compile(r"\[\[SEC:([A-Z_]+) id=(\d+)\]\]")
_WINDOW_LINES = 10
_WINDOW_CHARS = 1000


def _token_lines(lines: list[str]) -> dict[int, tuple[str, int]]:
    tokens: dict[int, tuple[str, int]] = {}
    for index, line in enumerate(lines):
        match = _TOKEN_RE.fullmatch(line.strip())
        if match:
            tokens[index] = (match.group(1), int(match.group(2)))
    return tokens


def _break_events(
    analysis, lines: list[str], tokens: dict[int, tuple[str, int]]
) -> tuple[dict[int, dict], int]:
    """Join annotate tokens to their marker namespaces by line alignment.

    The annotated text derives from ``analysis.source_text`` by span
    replacement (marker tokens) and insertion (inferred boundaries);
    every other line is verbatim. Aligning the two line sequences
    attributes each token to the source span it replaced — the markers
    intersecting that span are its members. A token the alignment
    cannot attribute stays unresolved and is counted, never guessed.
    """
    if analysis is None or not analysis.source_text:
        return {}, len(tokens)

    source_lines = [line.rstrip() for line in analysis.source_text.split("\n")]
    line_starts: list[int] = []
    offset = 0
    for line in analysis.source_text.split("\n"):
        line_starts.append(offset)
        offset += len(line) + 1
    markers = sorted(
        (m for m in analysis.markers if m.coordinate_frame == "text"),
        key=lambda m: (m.start, m.end),
    )
    boundaries = sorted(analysis.inferred_boundaries, key=lambda b: b.line)
    resolved: dict[int, dict] = {}
    unresolved = 0
    boundary_cursor = 0

    def attribute(token_id: int, span_start: int, span_end: int) -> None:
        members = [m for m in markers if m.start < span_end and m.end > span_start]
        if not members:
            resolved[token_id] = {
                "namespace": None,
                "page_number": None,
                "source": "marker",
            }
            return
        page_number = next(
            (m.page_number for m in members if m.page_number is not None), None
        )
        resolved[token_id] = {
            "namespace": (members[0].namespace or None),
            "page_number": page_number,
            "source": "marker",
        }

    matcher = difflib.SequenceMatcher(None, source_lines, list(lines), autojunk=False)
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        block_tokens = [j for j in range(b1, b2) if j in tokens]
        if not block_tokens:
            continue
        if tag == "insert":
            for j in block_tokens:
                token_id = tokens[j][1]
                if boundary_cursor < len(boundaries):
                    boundary = boundaries[boundary_cursor]
                    boundary_cursor += 1
                    resolved[token_id] = {
                        "namespace": (boundary.namespace or None),
                        "page_number": boundary.page_number,
                        "source": "inferred",
                    }
                else:
                    unresolved += 1
        elif tag == "replace":
            if len(block_tokens) == 1 and a2 > a1:
                j = block_tokens[0]
                attribute(
                    tokens[j][1],
                    line_starts[a1],
                    line_starts[a2 - 1] + len(source_lines[a2 - 1]),
                )
                continue
            # Pair each token with the source lines skipped before the
            # next verbatim line in the block; if any verbatim line has
            # no source counterpart, the block's tokens stay unresolved.
            src_cursor = a1
            pending: list[tuple[int, int, int]] = []
            failed = False
            for j in range(b1, b2):
                if j in tokens:
                    pending.append((tokens[j][1], src_cursor, src_cursor))
                    continue
                found = None
                for probe in range(src_cursor, a2):
                    if source_lines[probe] == lines[j]:
                        found = probe
                        break
                if found is None:
                    failed = True
                    break
                if len(pending) == 1:
                    token_id, span_lo, _ = pending[0]
                    pending[0] = (token_id, span_lo, found)
                elif len(pending) > 1:
                    # Consecutive tokens share the skipped span; which
                    # lines belong to which token is not recoverable.
                    failed = True
                    break
                src_cursor = found + 1
            if pending and not failed:
                if len(pending) == 1:
                    token_id, span_lo, _ = pending[0]
                    pending[0] = (token_id, span_lo, a2)
                else:
                    failed = True
            if failed:
                unresolved += len(block_tokens)
            else:
                for token_id, span_lo, span_hi in pending:
                    if span_hi > span_lo:
                        attribute(
                            token_id,
                            line_starts[span_lo],
                            line_starts[span_hi - 1] + len(source_lines[span_hi - 1]),
                        )
                    else:
                        unresolved += 1
        else:  # equal: a literal token-shaped line in the source itself
            unresolved += len(block_tokens)
    return resolved, unresolved


def _locate(lines: list[str], target: list[str], cursor: int) -> tuple[int, int] | None:
    size = len(target)
    for index in range(cursor, len(lines) - size + 1):
        if lines[index] == target[0] and lines[index : index + size] == target:
            return index, index + size
    compact = [line for line in target if line]
    if not compact:
        return None
    index_of = [i for i in range(cursor, len(lines)) if lines[i]]
    values = [lines[i] for i in index_of]
    for pos in range(0, len(values) - len(compact) + 1):
        if values[pos : pos + len(compact)] == compact:
            return index_of[pos], index_of[pos + len(compact) - 1] + 1
    return None


def _scale(captions: list[str], titles: list[str]) -> dict | None:
    for text in [*captions, *titles]:
        for pattern, unit in SCALE_PATTERNS:
            match = pattern.search(text)
            if match:
                return {"phrase": match.group(0), "unit": unit}
    return None


def _span_bounds(spans: list, line: int) -> dict | None:
    """Containing span for ``line``, else the nearest preceding one."""
    preceding = None
    for index, span in enumerate(spans):
        end = span.end_line
        if end is None:
            end = spans[index + 1].start_line if index + 1 < len(spans) else None
        if span.start_line <= line and (end is None or line < end):
            return span
        if span.start_line <= line:
            preceding = span
    return preceding


def _prose_window(
    lines: list[str], edge: int, spans: list[tuple[int, int]], *, before: bool
) -> str:
    picked: list[str] = []
    total = 0
    walk = range(edge - 1, -1, -1) if before else range(edge, len(lines))
    for index in walk:
        if any(start <= index < end for start, end in spans):
            break
        line = lines[index]
        if _TOKEN_RE.fullmatch(line.strip()) or not line.strip():
            continue
        picked.append(line.strip())
        total += len(line)
        if len(picked) >= _WINDOW_LINES or total >= _WINDOW_CHARS:
            break
    if before:
        picked.reverse()
    return "\n".join(picked)


def extract_filing(
    spec: dict, raw: bytes, document_path: str, *, tree: str
) -> tuple[dict, list[dict], dict]:
    """Build one successor fixture record from primary bytes.

    Returns the record, filing-level defect entries as plain dicts, and
    the normalize/extract timing split. Fetch timing is the caller's.
    """
    accession = str(spec["accession"])
    record: dict = {
        "accession": accession,
        "cik": spec["cik"],
        "form": spec["form"],
        "filing_date": spec["filing_date"],
        "era": spec["era"],
        "is_xbrl": spec["is_xbrl"],
        "filer_category": spec.get("filer_category"),
        "population": "retained-409",
        "status": "ok",
        "error": None,
        "builder": {
            "tool": "tools/table_extraction_corpus",
            "policy": "annotate",
            "tree": tree,
            "primary_document": spec.get("primary_document"),
            "primary_source": spec.get("primary_source"),
        },
        "geometries": [],
    }
    entries: list[dict] = []

    def note(defect_class: str, explanation: str, **kwargs) -> None:
        entry = {
            "class": defect_class,
            "stage": "extract",
            "accession": accession,
            "table_index": kwargs.get("table_index"),
            "count": 1,
            "specimens": [kwargs["specimen"]] if kwargs.get("specimen") else [],
            "explanation": explanation,
        }
        entries.append(entry)

    started = time.perf_counter()
    result: NormalizationResult = normalize_document(
        raw,
        form=str(spec["form"]),
        document_path=document_path,
        page_policy=PageArtifactPolicy.ANNOTATE,
    )
    normalize_s = time.perf_counter() - started
    extract_started = time.perf_counter()

    lines = [line.rstrip() for line in result.text.split("\n")]
    tokens = _token_lines(lines)
    namespace_by_id, unresolved_breaks = _break_events(
        result.page_analysis, lines, tokens
    )
    if unresolved_breaks:
        note(
            "break-namespace-unresolved",
            "the line alignment between the annotated text and the "
            "page analysis source could not attribute every token to a "
            "marker span; unattributed break namespaces are recorded "
            "as null",
            specimen=f"tokens={len(tokens)} unresolved={unresolved_breaks}",
        )

    labels = {lab["table_index"]: lab for lab in spec.get("labels", [])}
    sections = list(result.sections.sections) if result.sections else []
    notes = list(result.notes.notes) if result.notes else []

    spans: list[tuple[int, int] | None] = []
    rendered_sets: list[list[str]] = []
    cursor = 0
    for geometry in result.table_geometries:
        rendered = [
            line.rstrip() for line in geometry.render_result.ascii_text.split("\n")
        ]
        while rendered and not rendered[0]:
            rendered.pop(0)
        while rendered and not rendered[-1]:
            rendered.pop()
        rendered_sets.append(rendered)
        span = _locate(lines, rendered, cursor) if rendered else None
        spans.append(span)
        if span is not None:
            cursor = span[0]

    span_list = [span for span in spans if span is not None]
    geometries: list[dict] = []
    for geometry, span, rendered in zip(
        result.table_geometries, spans, rendered_sets, strict=True
    ):
        rows = [list(row) for row in geometry.rows]
        captions = list(parse_caption_stack(tuple(tuple(row) for row in rows)).lines)
        issues: list[str] = []
        section = _span_bounds(sections, span[0]) if span else None
        note_span = _span_bounds(notes, span[0]) if span else None
        titles = [
            title
            for title in (
                section.title if section else None,
                note_span.title if note_span else None,
            )
            if title
        ]
        if span is None:
            issues.append("geometry-not-located")
            note(
                "geometry-not-located",
                "the geometry's rendered lines were not found in the "
                "annotated text frame by ordered sequential search",
                table_index=geometry.table_index,
                specimen=(rendered[0] if rendered else "")[:120],
            )
            location = None
            prose_before = ""
            prose_after = ""
            breaks = {"inside": [], "before": None, "after": None}
        else:
            location = {"start_line": span[0], "end_line": span[1]}
            prose_before = _prose_window(lines, span[0], span_list, before=True)
            prose_after = _prose_window(lines, span[1], span_list, before=False)
            breaks = {"inside": [], "before": None, "after": None}
            for line_index in sorted(tokens):
                kind, token_id = tokens[line_index]
                event = namespace_by_id.get(token_id, {})
                item = {
                    "line": line_index,
                    "token": kind,
                    "id": token_id,
                    "namespace": event.get("namespace"),
                    "page_number": event.get("page_number"),
                }
                if span[0] <= line_index < span[1]:
                    breaks["inside"].append(item)
                elif line_index < span[0]:
                    breaks["before"] = item
                elif breaks["after"] is None:
                    breaks["after"] = item
        label = labels.get(geometry.table_index)
        if label is None:
            issues.append("label-missing")
            note(
                "label-missing",
                "no retained-corpus label exists for this table_index",
                table_index=geometry.table_index,
            )
        geometries.append(
            {
                "table_index": geometry.table_index,
                "header_row_count": geometry.header_row_count,
                "confidence": geometry.confidence,
                "rows": rows,
                "caption_stack": captions,
                "scale": _scale(captions, titles),
                "location": location,
                "preceding": {
                    "section": (
                        {"item": section.item_identifier, "title": section.title}
                        if section
                        else None
                    ),
                    "note": (
                        {
                            "number": note_span.note_number,
                            "label": note_span.note_label,
                            "title": note_span.title,
                        }
                        if note_span
                        else None
                    ),
                },
                "prose_before": prose_before,
                "prose_after": prose_after,
                "structured_location": {
                    "item": section.item_identifier if section else None,
                    "note": note_span.note_number if note_span else None,
                },
                "breaks": breaks,
                "issues": issues,
                "label": label,
            }
        )
    record["geometries"] = geometries
    timing = {
        "normalize_s": round(normalize_s, 4),
        "extract_s": round(time.perf_counter() - extract_started, 4),
    }
    return record, entries, timing
