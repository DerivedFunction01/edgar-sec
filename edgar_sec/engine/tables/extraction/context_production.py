"""Context production: NormalizationResults in, TableContexts out.

The single production path for filing contexts (R4):
filing-level facts are computed once in document normalization and
carried here; no consumer re-derives them.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, replace

from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.engine.tables.extraction.context import (
    BreakEvidence,
    BreakRef,
    NoteRef,
    Scale,
    SectionRef,
    TableContext,
)
from edgar_sec.engine.tables.extraction.genre_seat import (
    exhibit_stub_cell,
    index_named_label,
)
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.regions import RegionPath, derive_regions
from edgar_sec.engine.tables.extraction.toc_gate import (
    grid_page_ref_share,
    page_ref_cell,
)
from edgar_sec.engine.tables.extraction.typed_rows import parse_caption_stack
from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.engine.tables.patterns import SCALE_PATTERNS

_TOKEN_RE = re.compile(r"\[\[SEC:([A-Z_]+) id=(\d+)\]\]")
_WINDOW_LINES = 10
_WINDOW_CHARS = 1000

SEAT_MDA = "mda"
SEAT_ITEM_1 = "item_1"
SEAT_SECTION = "section"


@dataclass(frozen=True, slots=True)
class SectionSeat:
    """One region-map seat: a section span and the seat it carries."""

    item: str | None
    part: str | None
    title: str | None
    start_line: int
    end_line: int | None
    seat: str


@dataclass(frozen=True, slots=True)
class FilingFacts:
    """Filing-level facts computed once in normalization, carried here."""

    source_document: str
    toc_span_source: tuple[int, int] | None
    closing_start: int | None
    closing_kind: str | None
    region_map: tuple[SectionSeat, ...]

    @classmethod
    def from_result(
        cls, result: NormalizationResult, source_document: str
    ) -> FilingFacts:
        """Carry one document's normalization facts, deriving nothing."""
        toc = result.toc_span_source
        closing = result.closing_span
        seats: list[SectionSeat] = []
        sections = result.sections.sections if result.sections else ()
        for section in sections:
            title = section.title or ""
            normalized_title = normalize_text(title)
            item_key = (section.item_identifier or "").strip().lower()
            item_key = item_key.removeprefix("item").strip().rstrip(".")
            if "management" in normalized_title and "discussion" in normalized_title:
                seat = SEAT_MDA
            elif item_key == "1":
                seat = SEAT_ITEM_1
            else:
                seat = SEAT_SECTION
            seats.append(
                SectionSeat(
                    item=section.item_identifier,
                    part=None,
                    title=section.title,
                    start_line=section.start_line,
                    end_line=section.end_line,
                    seat=seat,
                )
            )
        return cls(
            source_document=source_document,
            toc_span_source=(toc.start_line, toc.end_line) if toc is not None else None,
            closing_start=closing.start_line if closing is not None else None,
            closing_kind=closing.kind if closing is not None else None,
            region_map=tuple(seats),
        )

    def seat_at(self, line: int) -> SectionSeat | None:
        """The region-map seat containing ``line``, else the preceding."""
        preceding: SectionSeat | None = None
        for seat in self.region_map:
            end = seat.end_line
            if seat.start_line <= line and (end is None or line < end):
                return seat
            if seat.start_line <= line:
                preceding = seat
        return preceding

    def as_record(self) -> dict:
        """The serialized facts block a corpus record carries."""
        return {
            "source_document": self.source_document,
            "toc_span_source": list(self.toc_span_source)
            if self.toc_span_source
            else None,
            "closing_span": self.closing_start,
            "closing_kind": self.closing_kind,
            "region_map": [
                {
                    "item": seat.item,
                    "part": seat.part,
                    "title": seat.title,
                    "start_line": seat.start_line,
                    "end_line": seat.end_line,
                    "seat": seat.seat,
                }
                for seat in self.region_map
            ],
        }


@dataclass(frozen=True, slots=True)
class DocumentInput:
    """One document entering production: its name and normalize result."""

    source_document: str
    result: NormalizationResult


@dataclass(frozen=True, slots=True)
class ProducedDocument:
    """One document's produced contexts, records, and production report."""

    source_document: str
    facts: FilingFacts
    contexts: tuple[TableContext, ...]
    records: tuple[dict, ...]
    unresolved_breaks: int = 0
    token_count: int = 0
    not_located: tuple[int, ...] = ()
    not_located_specimens: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ProductionResult:
    """Every produced document, in input order."""

    documents: tuple[ProducedDocument, ...]

    @property
    def contexts(self) -> tuple[TableContext, ...]:
        """All contexts across documents, in production order."""
        return tuple(
            context for document in self.documents for context in document.contexts
        )


def _token_lines(lines: list[str]) -> dict[int, tuple[str, int]]:
    tokens: dict[int, tuple[str, int]] = {}
    for index, line in enumerate(lines):
        match = _TOKEN_RE.fullmatch(line.strip())
        if match:
            tokens[index] = (match.group(1), int(match.group(2)))
    return tokens


def _toc_span_in_annotated_frame(
    analysis, lines: list[str], source_span
) -> tuple[int, int] | None:
    """The carried TOC span mapped into the annotated frame.

    Normalize found the span once, in the source frame; line alignment
    carries it into the annotated frame. The finder never re-runs.
    """
    if analysis is None or not analysis.source_text or source_span is None:
        return None
    span = source_span
    source_lines = [line.rstrip() for line in analysis.source_text.split("\n")]
    matcher = difflib.SequenceMatcher(None, source_lines, list(lines), autojunk=False)
    mapping: dict[int, int] = {}
    for a_start, b_start, size in matcher.get_matching_blocks():
        for offset in range(size):
            mapping[a_start + offset] = b_start + offset
    start = mapping.get(span.start_line)
    end = mapping.get(span.end_line - 1)
    if start is None or end is None:
        return None
    return (start, end + 1)


def _break_events(
    analysis, lines: list[str], tokens: dict[int, tuple[str, int]]
) -> tuple[dict[int, dict], int]:
    """Join annotate tokens to marker namespaces by line alignment.

    Aligning the annotated text with its source attributes each token
    to the source span it replaced.
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


def _scale(captions: list[str], titles: list[str]) -> Scale | None:
    for text in [*captions, *titles]:
        for pattern, unit in SCALE_PATTERNS:
            match = pattern.search(text)
            if match:
                return Scale(match.group(0), unit)
    return None


def _span_bounds(spans: list, line: int):
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


def _break_ref(item: dict | None) -> BreakRef | None:
    if item is None:
        return None
    return BreakRef(
        line=item["line"],
        token=item["token"],
        artifact_id=item["id"],
        namespace=item.get("namespace"),
        page_number=item.get("page_number"),
    )


def _grid_facts(rows: list[list[str]]) -> dict:
    """One geometry's genre facts, measured once over its raw grid."""
    grid_rows = 0
    max_row_cells = 0
    numeric_cells = 0
    data_rows = 0
    named = 0
    exhibit = 0
    page_ref_only = True
    for row in rows:
        cells = [cell.strip() for cell in row if cell.strip()]
        if not cells:
            continue
        grid_rows += 1
        max_row_cells = max(max_row_cells, len(cells))
        row_numeric = 0
        for cell in cells:
            if is_numeric_cell(cell):
                row_numeric += 1
                if not page_ref_cell(cell):
                    page_ref_only = False
        numeric_cells += row_numeric
        if row_numeric:
            data_rows += 1
        if index_named_label(cells[0]):
            named += 1
        if exhibit_stub_cell(cells[0]):
            exhibit += 1
    return {
        "numeric_cells": numeric_cells,
        "data_rows": data_rows,
        "grid_rows": grid_rows,
        "max_row_cells": max_row_cells,
        "index_named_share": named / grid_rows if grid_rows else 0.0,
        "page_ref_share": grid_page_ref_share(tuple(tuple(row) for row in rows)),
        "page_ref_only": page_ref_only,
        "exhibit_stub_share": exhibit / grid_rows if grid_rows else 0.0,
    }


def _produce_document(document: DocumentInput) -> ProducedDocument:
    """Produce one document's contexts and their serialized records."""
    result = document.result
    facts = FilingFacts.from_result(result, document.source_document)
    lines = [line.rstrip() for line in result.text.split("\n")]
    toc_span = _toc_span_in_annotated_frame(
        result.page_analysis, lines, result.toc_span_source
    )
    tokens = _token_lines(lines)
    namespace_by_id, unresolved_breaks = _break_events(
        result.page_analysis, lines, tokens
    )
    sections = list(result.sections.sections) if result.sections else []
    notes = list(result.notes.notes) if result.notes else []
    closing_start = facts.closing_start

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

    contexts: list[TableContext] = []
    records: list[dict] = []
    not_located: list[int] = []
    not_located_specimens: list[tuple[int, str]] = []
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
        scale = _scale(captions, titles)
        if span is None:
            issues.append("geometry-not-located")
            not_located.append(geometry.table_index)
            not_located_specimens.append(
                (geometry.table_index, (rendered[0] if rendered else "")[:120])
            )
            location = None
            prose_before = ""
            prose_after = ""
            breaks: dict = {"inside": [], "before": None, "after": None}
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
        in_toc = bool(
            location is not None
            and toc_span is not None
            and location["start_line"] < toc_span[1]
            and location["end_line"] >= toc_span[0]
        )
        in_closing = bool(
            location is not None
            and closing_start is not None
            and location["start_line"] >= closing_start
        )
        front_matter = bool(
            location is not None
            and facts.region_map
            and location["start_line"] < facts.region_map[0].start_line
        )
        grid_facts = _grid_facts(rows)
        section_ref = (
            SectionRef(
                section.item_identifier,
                section.title,
                getattr(section, "form", None),
                getattr(section, "part", None),
            )
            if section
            else None
        )
        note_ref = (
            NoteRef(note_span.note_number, note_span.note_label, note_span.title)
            if note_span
            else None
        )
        seat_obj = facts.seat_at(span[0]) if span is not None else None
        seat_name = seat_obj.seat if seat_obj is not None else None
        contexts.append(
            TableContext(
                geometry=geometry,
                caption_stack=tuple(captions),
                scale=scale,
                location=(location["start_line"], location["end_line"])
                if location
                else None,
                section=section_ref,
                note=note_ref,
                prose_before=prose_before,
                prose_after=prose_after,
                breaks=BreakEvidence(
                    inside=tuple(
                        ref
                        for ref in (
                            _break_ref(item) for item in breaks.get("inside") or ()
                        )
                        if ref is not None
                    ),
                    before=_break_ref(breaks.get("before")),
                    after=_break_ref(breaks.get("after")),
                ),
                issues=tuple(issues),
                in_toc_span=in_toc,
                in_closing_span=in_closing,
                closing_kind=facts.closing_kind if in_closing else None,
                source_document=document.source_document,
                seat=seat_name,
                front_matter=front_matter,
                **grid_facts,
            )
        )
        records.append(
            {
                "table_index": geometry.table_index,
                "header_row_count": geometry.header_row_count,
                "confidence": geometry.confidence,
                "rows": rows,
                "caption_stack": captions,
                "scale": {"phrase": scale.phrase, "unit": scale.unit}
                if scale
                else None,
                "location": location,
                "in_toc_span": in_toc,
                "in_closing_span": in_closing,
                "closing_kind": facts.closing_kind if in_closing else None,
                "source_document": document.source_document,
                "seat": seat_name,
                "front_matter": front_matter,
                **grid_facts,
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
            }
        )
    regions = derive_regions(contexts)
    contexts = [
        replace(
            context,
            region=region,
            region_path=RegionPath.DERIVED.value,
        )
        for context, region in zip(contexts, regions, strict=True)
    ]
    for record, region in zip(records, regions, strict=True):
        record["region"] = region
        record["region_path"] = RegionPath.DERIVED.value
    return ProducedDocument(
        source_document=document.source_document,
        facts=facts,
        contexts=tuple(contexts),
        records=tuple(records),
        unresolved_breaks=unresolved_breaks,
        token_count=len(tokens),
        not_located=tuple(not_located),
        not_located_specimens=tuple(not_located_specimens),
    )


def produce_contexts(
    documents: DocumentInput | tuple[DocumentInput, ...] | list[DocumentInput],
) -> ProductionResult:
    """Produce contexts for one filing's documents from normalize results.

    The one context-production function: every consumer
    calls this; none assembles a context of its own.
    """
    if isinstance(documents, DocumentInput):
        documents = (documents,)
    return ProductionResult(
        documents=tuple(_produce_document(document) for document in documents)
    )
