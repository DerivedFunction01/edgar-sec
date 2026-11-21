"""Computed-products serialization for one normalized document.

Capture stores what normalization computed — text, page analysis,
sections/notes, geometries — so work above the normalize line replays
against the products and never re-normalizes.
"""

from __future__ import annotations

from edgar_sec.engine.document.page_markers.models import (
    InferredBoundary,
    PageMarker,
    PageMarkerAnalysis,
)
from edgar_sec.engine.forms.cover.closing import ClosingSpan
from edgar_sec.engine.forms.cover.models import BoundaryMethod, CoverBoundary
from edgar_sec.engine.forms.cover.toc.models import TocEvidence, TocSpan
from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    NotesSequence,
    ResolvedNote,
    ResolvedSection,
    SectionSequence,
)
from edgar_sec.engine.tables.ascii_html.model.model import (
    HorizontalAlign,
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)

PRODUCTS_FORMAT = 1


def serialize_result(result: NormalizationResult) -> dict:
    """Serialize one result's computed products to a plain record."""
    return {
        "format": PRODUCTS_FORMAT,
        "text": result.text,
        "family": result.family,
        "representation": result.representation,
        "toc_span_source": _toc(result.toc_span_source),
        "closing_span": _closing(result.closing_span),
        "page_analysis": _analysis(result.page_analysis),
        "sections": _sections(result.sections),
        "notes": _notes(result.notes),
        "geometries": [_geometry(item) for item in result.table_geometries],
    }


def deserialize_result(products: dict) -> NormalizationResult:
    """Rebuild a result from stored products, normalizing nothing."""
    if products.get("format") != PRODUCTS_FORMAT:
        raise ValueError(f"unsupported products format: {products.get('format')!r}")
    return NormalizationResult(
        text=str(products["text"]),
        family=str(products["family"]),
        representation=str(products["representation"]),
        cover_boundary=CoverBoundary(
            end_line=None,
            end_offset=None,
            method=BoundaryMethod.DISABLED,
            confidence=0.0,
            approximate=True,
        ),
        toc_span_source=_toc_back(products.get("toc_span_source")),
        closing_span=_closing_back(products.get("closing_span")),
        page_analysis=_analysis_back(products.get("page_analysis")),
        sections=_sections_back(products.get("sections")),
        notes=_notes_back(products.get("notes")),
        table_geometries=tuple(
            _geometry_back(item) for item in products.get("geometries") or ()
        ),
    )


def _toc(span: TocSpan | None) -> dict | None:
    if span is None:
        return None
    return {
        "start_line": span.start_line,
        "end_line": span.end_line,
        "start_offset": span.start_offset,
        "end_offset": span.end_offset,
        "method": span.method,
        "confidence": span.confidence,
        "approximate": span.approximate,
        "evidence": [
            {"name": item.name, "line": item.line, "details": item.details}
            for item in span.evidence
        ],
    }


def _toc_back(record: dict | None) -> TocSpan | None:
    if record is None:
        return None
    return TocSpan(
        start_line=int(record["start_line"]),
        end_line=int(record["end_line"]),
        start_offset=int(record["start_offset"]),
        end_offset=int(record["end_offset"]),
        method=str(record["method"]),
        confidence=float(record["confidence"]),
        approximate=bool(record.get("approximate", False)),
        evidence=tuple(
            TocEvidence(
                name=str(item["name"]),
                line=item.get("line"),
                details=str(item.get("details", "")),
            )
            for item in record.get("evidence") or ()
        ),
    )


def _closing(span: ClosingSpan | None) -> dict | None:
    if span is None:
        return None
    return {
        "start_line": span.start_line,
        "kind": span.kind,
        "confidence": span.confidence,
        "approximate": span.approximate,
    }


def _closing_back(record: dict | None) -> ClosingSpan | None:
    if record is None:
        return None
    return ClosingSpan(
        start_line=int(record["start_line"]),
        kind=str(record["kind"]),
        confidence=float(record["confidence"]),
        approximate=bool(record.get("approximate", True)),
    )


def _analysis(analysis: PageMarkerAnalysis | None) -> dict | None:
    if analysis is None:
        return None
    return {
        "source_text": analysis.source_text,
        "representation": analysis.representation,
        "coordinate_frame": analysis.coordinate_frame,
        "markers": [
            {
                "start": marker.start,
                "end": marker.end,
                "text": marker.text,
                "kind": marker.kind,
                "page_number": marker.page_number,
                "page_count": marker.page_count,
                "representation": marker.representation,
                "confidence": marker.confidence,
                "start_line": marker.start_line,
                "end_line": marker.end_line,
                "namespace": marker.namespace,
                "family": marker.family,
                "evidence": list(marker.evidence),
                "coordinate_frame": marker.coordinate_frame,
                "node_path": list(marker.node_path),
            }
            for marker in analysis.markers
        ],
        "inferred_boundaries": [
            {
                "line": boundary.line,
                "page_number": boundary.page_number,
                "namespace": boundary.namespace,
                "reason": boundary.reason,
            }
            for boundary in analysis.inferred_boundaries
        ],
    }


def _analysis_back(record: dict | None) -> PageMarkerAnalysis | None:
    if record is None:
        return None
    return PageMarkerAnalysis(
        markers=tuple(
            PageMarker(
                start=int(item["start"]),
                end=int(item["end"]),
                text=str(item["text"]),
                kind=str(item["kind"]),
                page_number=item.get("page_number"),
                page_count=item.get("page_count"),
                representation=str(item.get("representation", "ascii")),
                confidence=float(item.get("confidence", 1.0)),
                start_line=item.get("start_line"),
                end_line=item.get("end_line"),
                namespace=str(item.get("namespace", "")),
                family=str(item.get("family", "")),
                evidence=tuple(item.get("evidence") or ()),
                coordinate_frame=str(item.get("coordinate_frame", "text")),
                node_path=tuple(item.get("node_path") or ()),
            )
            for item in record.get("markers") or ()
        ),
        decisions=(),
        page_boundaries=(),
        representation=str(record.get("representation", "ascii")),
        source_text=str(record.get("source_text", "")),
        coordinate_frame=str(record.get("coordinate_frame", "text")),
        inferred_boundaries=tuple(
            InferredBoundary(
                line=float(item["line"]),
                page_number=item.get("page_number"),
                namespace=str(item["namespace"]),
                reason=str(item["reason"]),
            )
            for item in record.get("inferred_boundaries") or ()
        ),
    )


def _sections(sequence: SectionSequence | None) -> dict | None:
    if sequence is None:
        return None
    return {
        "family": sequence.family,
        "missing_items": list(sequence.missing_items),
        "renderer_version": sequence.renderer_version,
        "sections": [
            {
                "item_identifier": section.item_identifier,
                "start_line": section.start_line,
                "end_line": section.end_line,
                "title": section.title,
                "raw_heading": section.raw_heading,
                "kind": section.kind.value,
                "confidence": section.confidence,
                "is_omitted": section.is_omitted,
                "grouped_with": list(section.grouped_with),
                "start_char": section.start_char,
                "end_char": section.end_char,
                "displaced": section.displaced,
            }
            for section in sequence.sections
        ],
    }


def _sections_back(record: dict | None) -> SectionSequence | None:
    if record is None:
        return None
    return SectionSequence(
        family=str(record["family"]),
        missing_items=tuple(record.get("missing_items") or ()),
        renderer_version=record.get("renderer_version"),
        sections=tuple(
            ResolvedSection(
                item_identifier=str(item["item_identifier"]),
                start_line=int(item["start_line"]),
                end_line=item.get("end_line"),
                title=str(item["title"]),
                raw_heading=str(item["raw_heading"]),
                kind=CandidateKind(str(item["kind"])),
                confidence=float(item["confidence"]),
                is_omitted=bool(item.get("is_omitted", False)),
                grouped_with=tuple(item.get("grouped_with") or ()),
                start_char=item.get("start_char"),
                end_char=item.get("end_char"),
                displaced=bool(item.get("displaced", False)),
            )
            for item in record.get("sections") or ()
        ),
    )


def _notes(sequence: NotesSequence | None) -> dict | None:
    if sequence is None:
        return None
    return {
        "renderer_version": sequence.renderer_version,
        "notes": [
            {
                "note_number": note.note_number,
                "note_label": note.note_label,
                "start_line": note.start_line,
                "end_line": note.end_line,
                "title": note.title,
                "raw_heading": note.raw_heading,
                "confidence": note.confidence,
                "grouped_with": list(note.grouped_with),
                "start_char": note.start_char,
                "end_char": note.end_char,
            }
            for note in sequence.notes
        ],
    }


def _notes_back(record: dict | None) -> NotesSequence | None:
    if record is None:
        return None
    return NotesSequence(
        renderer_version=record.get("renderer_version"),
        notes=tuple(
            ResolvedNote(
                note_number=int(item["note_number"]),
                note_label=str(item["note_label"]),
                start_line=int(item["start_line"]),
                end_line=item.get("end_line"),
                title=str(item["title"]),
                raw_heading=str(item["raw_heading"]),
                confidence=float(item["confidence"]),
                grouped_with=tuple(item.get("grouped_with") or ()),
                start_char=item.get("start_char"),
                end_char=item.get("end_char"),
            )
            for item in record.get("notes") or ()
        ),
    )


def _geometry(geometry: TableGeometry) -> dict:
    grid = geometry.resolved_grid
    render = geometry.render_result
    return {
        "table_index": geometry.table_index,
        "ascii_text": render.ascii_text,
        "rows": [list(row) for row in grid.rows],
        "column_alignments": [item.value for item in grid.column_alignments],
        "column_widths": list(grid.column_widths),
        "header_row_count": grid.header_row_count,
        "grid_confidence": grid.confidence,
        "confidence": render.confidence,
        "diagnostics": list(render.diagnostics),
        "is_fallback": render.is_fallback,
    }


def _geometry_back(record: dict) -> TableGeometry:
    grid = ResolvedGrid(
        rows=tuple(tuple(str(cell) for cell in row) for row in record["rows"]),
        column_alignments=tuple(
            HorizontalAlign(str(item)) for item in record.get("column_alignments") or ()
        ),
        column_widths=tuple(int(item) for item in record.get("column_widths") or ()),
        header_row_count=int(record.get("header_row_count", 0)),
        confidence=float(record.get("grid_confidence", 1.0)),
    )
    render = TableRenderResult(
        ascii_text=str(record["ascii_text"]),
        resolved_grid=grid,
        confidence=float(record["confidence"]),
        diagnostics=tuple(record.get("diagnostics") or ()),
        is_fallback=bool(record.get("is_fallback", False)),
    )
    return TableGeometry(table_index=int(record["table_index"]), render_result=render)
