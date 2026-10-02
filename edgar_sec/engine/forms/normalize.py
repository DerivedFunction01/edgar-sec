"""Central document normalization seam connecting raw bytes to normalized text.

This module owns the *stage order* and the result record. Every algorithm lives
in a leaf package: `engine.document` for input preparation, HTML, page
markers, and whitespace, `engine.tables` for table handling, and
`engine.forms.cover` for the cover decision chain. The types those stages
produce are declared where they are produced and imported here — this module
re-declares nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

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
    CoverBoundary,
)
from edgar_sec.engine.forms.cover.profiles import get_profile
from edgar_sec.engine.forms.cover.reflow import (
    is_checkbox_answer_line,
    is_cover_layout_line,
)
from edgar_sec.engine.forms.cover.tables.cleaner import clean_cover_tables
from edgar_sec.engine.forms.cover.toc.finder import find_toc_span
from edgar_sec.engine.forms.cover.toc.models import TocSpan
from edgar_sec.engine.reflow.engine.mapper import build_line_mapper
from edgar_sec.engine.reflow.engine.rewrapper import reflow_ascii
from edgar_sec.engine.reflow.types import ReflowPolicy, ReflowResult
from edgar_sec.engine.tables.ascii_html.model import TableGeometry


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
    stage_trace: list[StageRecord] = field(default_factory=list)


def normalize_document(
    raw_bytes: bytes,
    *,
    form: str | None = None,
) -> NormalizationResult:
    """Normalize one raw filing payload.

    Stages run in canonical order and every stage records a `StageRecord`
    carrying its own output digest, line count, and character count.
    """
    text, representation, _encoding = prepare_input_text(raw_bytes)

    stage_trace: list[StageRecord] = []
    stage_trace.append(StageRecord.of("unpacked", text))

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
        ) = apply_fast_html_page_policy(text)
        stage_trace.append(StageRecord.of("html_cleaned", text))
    else:
        text, analysis, _artifacts, _templates, _next_id = apply_text_policy(text)

    stage_trace.append(StageRecord.of("page_policy", text))

    canonical_family = resolve_alias(form)
    family = canonical_family or (form.upper().strip() if form else "GENERIC")
    profile = get_profile(canonical_family)

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
    stage_trace.append(StageRecord.of("cover_boundary", text))

    text, pair_changed = normalize_yes_no_pairs(
        text,
        start_line=boundary.start_line or 0,
        end_line=boundary.end_line,
    )
    if pair_changed:
        stage_trace.append(StageRecord.of("after_yes_no_pair_normalization", text))

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
        if checkmark_changed:
            stage_trace.append(StageRecord.of("after_checkmark_rewrite", text))

    if profile.cover_table_cleaners and boundary.end_line is not None:
        cleaned_cover_text, table_geometries = clean_cover_tables(
            text,
            boundary,
            table_geometries=table_geometries,
            enabled_cleaners=profile.cover_table_cleaners,
        )
        if cleaned_cover_text != text:
            text = cleaned_cover_text
            stage_trace.append(StageRecord.of("after_cover_table_cleaning", text))

    healed_text, cover_changed = heal_cover_text(
        text,
        boundary,
        tuple(profile.healing_rules),
        merge_binary_blocks=(representation is Representation.HTML),
        reflow_prose=False,
    )
    if cover_changed:
        text = healed_text
        stage_trace.append(StageRecord.of("after_cover_healing", text))

    text = normalize_final_text_whitespace(text)
    stage_trace.append(StageRecord.of("after_final_whitespace", text))

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
    if representation is not Representation.HTML and body_start_line > 0:
        stage_trace.append(StageRecord.of("before_reflow", text))
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
            body_start_line=body_start_line,
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
        stage_trace.append(StageRecord.of("after_reflow", text))

    closing_search_from = (
        (body_start.first_unit_line + 1)
        if (body_start is not None and body_start.first_unit_line is not None)
        else 0
    )
    closing_span = find_closing_span(text, search_from=closing_search_from)

    return NormalizationResult(
        text=text.strip(),
        family=family,
        representation=("html" if representation is Representation.HTML else "ascii"),
        cover_boundary=boundary,
        cover_boundary_detected_line=detected_cover_end,
        cover_start_detected_line=detected_cover_start,
        body_start=body_start,
        toc_span=toc_span,
        closing_span=closing_span,
        page_analysis=analysis,
        reflow=reflow_result,
        table_geometries=table_geometries,
        stage_trace=stage_trace,
    )


__all__ = [
    "NormalizationResult",
    "normalize_document",
]
