"""Central document normalization seam: raw bytes to normalized text. Owns the stage
order and the result record; every algorithm lives in a leaf package
(`engine.document`, `engine.tables`, `engine.forms.cover`).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from edgar_sec.domain.document.route import (
    REPRESENTATION_ASCII,
    REPRESENTATION_HTML,
    REPRESENTATION_XML,
    DocumentRoute,
    document_route,
)
from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.models import StageRecord
from edgar_sec.domain.taxonomy.statements.predicates import (
    is_financial_table_bridge_line,
    is_financial_table_tail_line,
)
from edgar_sec.engine.document.page_markers.detector import is_page_marker_line
from edgar_sec.engine.document.page_markers.models import PageMarkerAnalysis
from edgar_sec.engine.document.page_markers.policy import (
    apply_fast_html_page_policy,
    apply_text_policy,
)
from edgar_sec.engine.document.unpacking.representation import (
    Representation,
    prepare_input_text,
)
from edgar_sec.engine.document.whitespace.normalizer import (
    normalize_final_text_whitespace,
)
from edgar_sec.engine.forms.cover.body_start import find_body_start
from edgar_sec.engine.forms.cover.boundary.detector import (
    find_cover_boundary_for_profile,
)
from edgar_sec.engine.forms.cover.checkmarks.models import CoverCheckmarkResult
from edgar_sec.engine.forms.cover.checkmarks.rewrite import (
    apply_cover_checkmark_decisions,
    has_labeled_checkmark_candidates,
    has_resolvable_line_yes_no_candidates,
    update_table_geometries,
)
from edgar_sec.engine.forms.cover.checkmarks.solver import infer_cover_checkmarks
from edgar_sec.engine.forms.cover.checkmarks.yes_no_pairs import normalize_yes_no_pairs
from edgar_sec.engine.forms.cover.closing import ClosingSpan, find_closing_span
from edgar_sec.engine.forms.cover.healing.text import heal_cover_text
from edgar_sec.engine.forms.cover.models import (
    BodyStart,
    BoundaryInput,
    BoundaryMethod,
    CoverBoundary,
)
from edgar_sec.engine.forms.cover.profiles import GENERIC_PROFILE_FAMILY, get_profile
from edgar_sec.engine.forms.cover.reflow import (
    is_checkbox_answer_line,
    is_cover_layout_line,
)
from edgar_sec.engine.forms.cover.tables.cleaner import clean_cover_tables
from edgar_sec.engine.forms.cover.toc.finder import find_toc_span
from edgar_sec.engine.forms.cover.toc.models import TocSpan
from edgar_sec.engine.forms.common.marks import canonicalize_filled_marks_in_span
from edgar_sec.engine.forms.sections.models import NotesSequence, SectionSequence
from edgar_sec.engine.reflow.engine.mapper import build_line_mapper
from edgar_sec.engine.reflow.engine.rewrapper import reflow_ascii
from edgar_sec.engine.reflow.types import ReflowPolicy, ReflowResult
from edgar_sec.engine.tables.ascii_html.model import TableGeometry


#: Routes carrying text eligible for prose reflow. Markup, XML, binary, and paper
#: routes are excluded by omission: only these two are ever normalized as prose.
_TEXT_ROUTES = frozenset({DocumentRoute.TEXT, DocumentRoute.UNKNOWN})


def _representation_name(route: DocumentRoute, detected: Representation) -> str:
    """Name the representation that was actually applied.

    The route overrides detection only where detection cannot see the format.
    """
    if route is DocumentRoute.XML:
        return REPRESENTATION_XML
    if detected is Representation.HTML:
        return REPRESENTATION_HTML
    return REPRESENTATION_ASCII


def _line_start_offset(text: str, line: int) -> int:
    offset = 0
    for _ in range(line):
        newline = text.find("\n", offset)
        if newline < 0:
            return len(text)
        offset = newline + 1
    return offset


def _trim_text_with_toc_span(
    text: str, toc_span: TocSpan | None
) -> tuple[str, TocSpan | None]:
    leading = len(text) - len(text.lstrip())
    leading_lines = text[:leading].count("\n")
    normalized = text.strip()
    if toc_span is None:
        return normalized, None

    start_line = max(0, toc_span.start_line - leading_lines)
    end_line = max(0, toc_span.end_line - leading_lines)
    return normalized, replace(
        toc_span,
        start_line=start_line,
        end_line=end_line,
        start_offset=_line_start_offset(normalized, start_line),
        end_offset=_line_start_offset(normalized, end_line),
    )


def _normalize_paper_stub(raw_bytes: bytes, *, form: str | None) -> NormalizationResult:
    """Record a paper submission without running the form-driven prose pipeline.

    Every ``.paper`` payload is one fixed SGML stub naming an off-archive Document
    Control Number; there is no filing prose to parse.
    """
    text, _representation, _encoding = prepare_input_text(raw_bytes)
    stripped = text.strip()
    canonical_family = resolve_alias(form)
    return NormalizationResult(
        text=stripped,
        family=canonical_family or (form.upper().strip() if form else "GENERIC"),
        representation=REPRESENTATION_ASCII,
        cover_boundary=CoverBoundary(
            end_line=None,
            end_offset=None,
            method=BoundaryMethod.DISABLED,
            confidence=0.0,
            approximate=True,
        ),
    )


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Final output of document normalization pipeline."""

    text: str
    family: str
    representation: str
    cover_boundary: CoverBoundary
    cover_boundary_detected_line: int | None = None
    cover_start_detected_line: int | None = None
    body_start: BodyStart | None = None
    toc_span: TocSpan | None = None
    closing_span: ClosingSpan | None = None
    page_analysis: PageMarkerAnalysis | None = None
    reflow: ReflowResult | None = None
    table_geometries: tuple[TableGeometry, ...] = ()
    cover_checkmarks: CoverCheckmarkResult | None = None
    sections: SectionSequence | None = None
    notes: NotesSequence | None = None


def normalize_document(
    raw_bytes: bytes,
    *,
    form: str | None = None,
    document_path: str | None = None,
    content_route: DocumentRoute | None = None,
) -> NormalizationResult:
    """Normalize one raw filing payload."""
    route = (
        content_route if content_route is not None else document_route(document_path)
    )
    if route is DocumentRoute.PAPER:
        return _normalize_paper_stub(raw_bytes, form=form)
    if route is DocumentRoute.BINARY:
        raise ValueError(
            f"route {route.value!r} carries no text; store the payload verbatim"
        )

    text, representation, _encoding = prepare_input_text(raw_bytes)

    canonical_family = resolve_alias(form)
    family = canonical_family or (form.upper().strip() if form else "GENERIC")
    profile = get_profile(canonical_family)

    table_geometries: tuple[TableGeometry, ...] = ()
    analysis: PageMarkerAnalysis | None = None

    if representation is Representation.HTML:
        (
            text,
            analysis,
            _artifacts,
            _templates,
            _next_id,
            table_geometries,
        ) = apply_fast_html_page_policy(
            text, unwrap_false_tables=profile.unwrap_false_tables
        )
    else:
        text, analysis, _artifacts, _templates, _next_id = apply_text_policy(text)

    boundary = find_cover_boundary_for_profile(
        BoundaryInput(
            text,
            representation=(
                "html" if representation is Representation.HTML else "ascii"
            ),
            page_analysis=analysis,
        ),
        profile,
    )
    detected_cover_end = boundary.end_line
    detected_cover_start = boundary.start_line

    text, _ = canonicalize_filled_marks_in_span(
        text,
        start_line=boundary.start_line or 0,
        end_line=boundary.end_line,
    )
    text, pair_changed = normalize_yes_no_pairs(
        text,
        start_line=boundary.start_line or 0,
        end_line=boundary.end_line,
    )

    checkmark_inference = infer_cover_checkmarks(
        text,
        boundary,
        family=profile.family,
        table_geometries=table_geometries,
        schema=profile.checkbox_schema,
    )
    if (
        checkmark_inference.decisions
        or has_labeled_checkmark_candidates(checkmark_inference.candidates)
        or has_resolvable_line_yes_no_candidates(checkmark_inference.candidates)
    ):
        text, checkmark_changed, unwrapped_indices = apply_cover_checkmark_decisions(
            text,
            checkmark_inference,
        )
        table_geometries = tuple(  # type: ignore[assignment]
            update_table_geometries(
                table_geometries,
                checkmark_inference,
                unwrapped_indices,
            )
        )

    if profile.cover_table_cleaners and boundary.end_line is not None:
        cleaned_cover_text, table_geometries = clean_cover_tables(
            text,
            boundary,
            table_geometries=table_geometries,
            enabled_cleaners=profile.cover_table_cleaners,
        )
        if cleaned_cover_text != text:
            text = cleaned_cover_text

    healed_text, cover_changed = heal_cover_text(
        text,
        boundary,
        tuple(profile.healing_rules),
        merge_binary_blocks=(representation is Representation.HTML),
        reflow_prose=False,
    )
    if cover_changed:
        text = healed_text

    text = normalize_final_text_whitespace(text)

    toc_span: TocSpan | None = None
    body_start: BodyStart | None = None

    if profile.boundary is not None:
        if profile.boundary.signals:
            toc_span = find_toc_span(
                text,
                start_line=boundary.start_line or 0,
                page_analysis=analysis,
                derived_taxonomy=profile.derived_taxonomy,
            )

        if profile.body_evidence is not None:
            body_start = find_body_start(
                text,
                cover_end=boundary.end_line,
                toc_end=toc_span.end_line if toc_span is not None else None,
                evidence=profile.body_evidence,
                toc_span=toc_span,
            )

    body_start_line = (
        body_start.first_unit_line
        if (body_start is not None and body_start.first_unit_line is not None)
        else max(
            (boundary.end_line or 0) if boundary else 0,
            (toc_span.end_line or 0) if toc_span else 0,
        )
    )

    reflow_result: ReflowResult | None = None
    reflow_eligible = route in _TEXT_ROUTES
    no_cover = profile.family == GENERIC_PROFILE_FAMILY
    if (
        reflow_eligible
        and representation is not Representation.HTML
        and (body_start_line > 0 or no_cover)
    ):
        reflow_policy = ReflowPolicy(
            unwrap_pre_body_prose=True,
            relax_prose_layout_gaps=True,
            unwrap_bullet_continuations=True,
            is_checkbox_answer_line=is_checkbox_answer_line,
            is_page_boundary_line=is_page_marker_line,
            is_structural_line=is_cover_layout_line,
            is_table_bridge_line=is_financial_table_bridge_line,
            is_table_tail_line=is_financial_table_tail_line,
        )
        reflow_result = reflow_ascii(
            text,
            body_start_line=0 if no_cover else body_start_line,
            page_analysis=analysis,
            policy=reflow_policy,
        )
        text = reflow_result.text
        map_line = build_line_mapper(reflow_result.decisions)
        if boundary.end_line is not None:
            boundary = replace(boundary, end_line=map_line(boundary.end_line))
        if boundary.start_line is not None:
            boundary = replace(boundary, start_line=map_line(boundary.start_line))
        if toc_span is not None:
            toc_span = replace(
                toc_span,
                start_line=map_line(toc_span.start_line),
                end_line=map_line(toc_span.end_line),
            )
        if body_start is not None:
            body_start = replace(
                body_start,
                line=map_line(body_start.line) if body_start.line is not None else None,
                heading_line=map_line(body_start.heading_line)
                if body_start.heading_line is not None
                else None,
                first_unit_line=map_line(body_start.first_unit_line)
                if body_start.first_unit_line is not None
                else None,
            )

    closing_search_from = (
        (body_start.first_unit_line + 1)
        if (body_start is not None and body_start.first_unit_line is not None)
        else 0
    )
    closing_span = find_closing_span(text, search_from=closing_search_from)

    text, toc_span = _trim_text_with_toc_span(text, toc_span)

    sections = None
    notes = None
    if profile.has_sections or profile.has_notes:
        from edgar_sec.foundation.hashing import sha256_text

        text_sha = sha256_text(text)
    else:
        text_sha = None

    if profile.has_sections:
        from edgar_sec.domain.forms.families.processing_profiles import (
            get_family_entry,
        )
        from edgar_sec.engine.forms.sections.items.detector import (
            detect_section_sequence,
        )

        entry = get_family_entry(family)
        taxonomy = entry.taxonomy_items if entry is not None else ()
        if taxonomy:
            raw_toc = (
                (toc_span.start_line, toc_span.end_line)
                if toc_span is not None
                else None
            )
            sections = detect_section_sequence(
                text,
                family=family,
                taxonomy_items=taxonomy,
                toc_span=raw_toc,
                payload_sha256=text_sha,
                renderer_version=profile.version,
            )

    if profile.has_notes:
        from edgar_sec.engine.forms.sections.notes.detector import (
            detect_notes_sequence,
        )

        notes = detect_notes_sequence(
            text,
            payload_sha256=text_sha,
            renderer_version=profile.version,
        )

    return NormalizationResult(
        text=text,
        family=family,
        representation=_representation_name(route, representation),
        cover_boundary=boundary,
        cover_boundary_detected_line=detected_cover_end,
        cover_start_detected_line=detected_cover_start,
        body_start=body_start,
        toc_span=toc_span,
        closing_span=closing_span,
        page_analysis=analysis,
        reflow=reflow_result,
        table_geometries=table_geometries,
        cover_checkmarks=checkmark_inference,
        sections=sections,
        notes=notes,
    )


__all__ = [
    "NormalizationResult",
    "normalize_document",
]
