"""Deep document normalization and form-aware SEC content standardization."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from defs.runtime.memory import sha256_text
from defs.sec_forms.cover import (
    BoundaryInput,
    CoverBoundary,
    apply_cover_checkmark_decisions,
    clean_cover_tables,
    find_body_start,
    find_closing_span,
    find_cover_boundary_for_profile,
    find_toc_span,
    get_profile,
    heal_cover_text,
    infer_cover_checkmarks,
    update_table_geometries,
)
from defs.sec_forms.cover.checkmark.rewrite import (
    _has_labeled_checkmark_candidates,
    _has_resolvable_line_yes_no_candidates,
)
from defs.sec_forms.cover.checkmark.yes_no_pairs import normalize_yes_no_pairs
from defs.sec_forms.cover.reflow import (
    is_checkbox_answer_line,
    is_cover_layout_line,
    is_page_marker_line,
)
from defs.sec_forms.page_markers import (
    PageArtifactPolicy,
    apply_html_policy,
    apply_text_policy,
    build_page_artifact_metadata,
)
from defs.taxonomy.components.financials.reflow import (
    is_financial_table_bridge_line,
    is_financial_table_tail_line,
)
from defs.text import count_lines, normalize_final_text_whitespace
from defs.text.reflow import (
    ReflowPolicy,
    build_line_mapper,
    reflow_ascii,
)

from .forms.base import PreprocessedDocument
from .router import FormRouter


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Normalized text plus structural metadata discovered during processing.

    ``cover_boundary`` is detected on the cover-healed representation while
    ``toc_span`` and ``body_start`` are resolved on the final normalized text.
    ``closing_span`` is the conservative start of the signature/exhibit tail,
    or ``None`` when no exact closing signal exists after the body.
    ``reflow`` is the ASCII span/action decision trace (empty for HTML input).
    ``checkmark_inference`` records form-scoped cover glyph hypotheses and
    decisions; no-cover profiles expose a ``not_applicable`` result.
    ``page_analysis`` is the immutable page-marker analysis of the canonical
    source frame, performed exactly once before marker removal.
    ``stage_trace`` records bounded metadata at each normalization stage.
    """

    text: str
    cover_boundary: CoverBoundary
    body_start: object | None = None
    toc_span: object | None = None
    closing_span: object | None = None
    reflow: object | None = None
    page_analysis: object | None = None
    page_artifacts: dict | None = None
    table_geometries: tuple = ()
    checkmark_inference: object | None = None
    stage_trace: tuple = ()


class DeepNormalizer:
    """Stage 3 normalizer; coordinates generic table and form-aware structural normalization."""

    def __init__(self, router: FormRouter | None = None) -> None:
        self._router = router or FormRouter()

    def normalize(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self.normalize_result(preprocessed, metadata).text

    def normalize_result(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
        *,
        page_artifact_policy: PageArtifactPolicy = PageArtifactPolicy.STRIP,
    ) -> NormalizationResult:
        """Normalize preprocessed document using form-specific and generic rules."""
        form = (metadata or {}).get("form") or preprocessed.metadata.get("form")
        form_normalizer = self._router.get_normalizer(form)
        profile = get_profile(form)
        representation = preprocessed.representation or (
            "html" if preprocessed.has_html_tags else "ascii"
        )
        is_html = representation == "html" or preprocessed.has_html_tags
        text = preprocessed.cleaned_text
        stage_trace: list[dict[str, Any]] = []

        source_identity = sha256_text(text)
        # Stage metadata reuse: equal text content implies equal identity and
        # line counts, so unchanged stages reuse the cached values instead of
        # re-hashing and re-counting multi-megabyte strings. The source
        # identity of the preprocessed text stays fixed for artifact metadata.
        cached_text = text
        cached_identity = source_identity
        cached_line_count = count_lines(text)

        def _stage_metadata(current_text: str) -> tuple[str, int]:
            nonlocal cached_text, cached_identity, cached_line_count
            if current_text is not cached_text and current_text != cached_text:
                cached_identity = sha256_text(current_text)
                cached_line_count = count_lines(current_text)
                cached_text = current_text
            return cached_identity, cached_line_count

        stage_trace.append(
            {
                "stage": "preprocessed",
                "text_identity": source_identity,
                "representation": representation,
                "line_count": cached_line_count,
                "char_count": len(text),
            }
        )

        artifact_templates: dict[str, dict] = {}
        artifact_records: list[tuple[int, object]] = []
        table_geometries: tuple = ()
        next_artifact_id = 1
        if is_html:
            first_html_id = next_artifact_id
            (
                text,
                page_analysis,
                html_artifacts,
                html_templates,
                next_artifact_id,
                table_geometries,
            ) = apply_html_policy(
                text,
                None,
                page_artifact_policy,
                first_id=first_html_id,
            )
            artifact_templates.update(html_templates)
            artifact_records.extend(
                zip(range(first_html_id, next_artifact_id), html_artifacts)
            )
        else:
            first_ascii_id = next_artifact_id
            input_identity, input_line_count = _stage_metadata(text)
            stage_trace.append(
                {
                    "stage": "page_policy_input",
                    "text_identity": input_identity,
                    "representation": representation,
                    "line_count": input_line_count,
                    "char_count": len(text),
                    "marker_count": 0,
                    "page_boundary_count": 0,
                    "page_number_run_count": 0,
                }
            )
            (
                text,
                page_analysis,
                ascii_artifacts,
                ascii_templates,
                next_artifact_id,
            ) = apply_text_policy(
                text,
                None,
                page_artifact_policy,
                first_id=first_ascii_id,
            )
            artifact_templates.update(ascii_templates)
            artifact_records.extend(
                zip(
                    range(first_ascii_id, next_artifact_id),
                    ascii_artifacts,
                )
            )

        output_identity, output_line_count = _stage_metadata(text)
        stage_trace.append(
            {
                "stage": "page_policy_output",
                "text_identity": output_identity,
                "representation": representation,
                "line_count": output_line_count,
                "char_count": len(text),
                "marker_count": len(getattr(page_analysis, "markers", ()))
                if page_analysis
                else 0,
                "page_boundary_count": len(
                    getattr(page_analysis, "page_boundaries", ())
                )
                if page_analysis
                else 0,
                "page_number_run_count": len(
                    getattr(page_analysis, "page_number_runs", ())
                )
                if page_analysis
                else 0,
            }
        )

        boundary = find_cover_boundary_for_profile(
            BoundaryInput(
                text,
                representation=representation,
                page_analysis=page_analysis,
            ),
            profile,
        )

        text, pair_changed = normalize_yes_no_pairs(
            text,
            start_line=boundary.start_line or 0,
            end_line=boundary.end_line,
        )
        if pair_changed:
            pair_identity, pair_line_count = _stage_metadata(text)
            stage_trace.append(
                {
                    "stage": "after_yes_no_pair_normalization",
                    "text_identity": pair_identity,
                    "representation": representation,
                    "line_count": pair_line_count,
                    "char_count": len(text),
                }
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
            or _has_labeled_checkmark_candidates(checkmark_inference.candidates)
            or _has_resolvable_line_yes_no_candidates(checkmark_inference.candidates)
        ):
            text, checkmark_changed, unwrapped_indices = (
                apply_cover_checkmark_decisions(
                    text,
                    checkmark_inference,
                )
            )
            table_geometries = update_table_geometries(
                table_geometries,
                checkmark_inference,
                unwrapped_indices,
            )
            if checkmark_changed:
                checkmark_identity, checkmark_line_count = _stage_metadata(text)
                stage_trace.append(
                    {
                        "stage": "after_checkmark_rewrite",
                        "text_identity": checkmark_identity,
                        "representation": representation,
                        "line_count": checkmark_line_count,
                        "char_count": len(text),
                    }
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
                cover_clean_identity, cover_clean_line_count = _stage_metadata(text)
                stage_trace.append(
                    {
                        "stage": "after_cover_table_cleaning",
                        "text_identity": cover_clean_identity,
                        "representation": representation,
                        "line_count": cover_clean_line_count,
                        "char_count": len(text),
                    }
                )

        healed_text, cover_changed = heal_cover_text(
            text,
            boundary,
            tuple(profile.healing_rules),
            merge_binary_blocks=is_html,
            reflow_prose=False,
        )
        if cover_changed:
            text = healed_text
            healing_identity, healing_line_count = _stage_metadata(text)
            stage_trace.append(
                {
                    "stage": "after_cover_healing",
                    "text_identity": healing_identity,
                    "representation": representation,
                    "line_count": healing_line_count,
                    "char_count": len(text),
                }
            )

        text = form_normalizer.normalize(text, metadata)

        text = normalize_final_text_whitespace(text)
        final_identity, final_line_count = _stage_metadata(text)
        stage_trace.append(
            {
                "stage": "after_final_whitespace",
                "text_identity": final_identity,
                "representation": representation,
                "line_count": final_line_count,
                "char_count": len(text),
            }
        )

        body_start = None
        toc_span = None
        closing_span = None
        reflow_result = None
        if profile.boundary is not None and profile.body_evidence is not None:
            toc_span = find_toc_span(
                text,
                start_line=boundary.start_line or 0,
                page_analysis=page_analysis,
                derived_taxonomy=profile.derived_taxonomy,
            )
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
        if not is_html and body_start_line > 0:
            reflow_input_identity, reflow_input_line_count = _stage_metadata(text)
            stage_trace.append(
                {
                    "stage": "before_reflow",
                    "text_identity": reflow_input_identity,
                    "representation": representation,
                    "line_count": reflow_input_line_count,
                    "char_count": len(text),
                }
            )
            reflow_result = reflow_ascii(
                text,
                body_start_line=body_start_line,
                page_analysis=page_analysis,
                policy=ReflowPolicy(
                    unwrap_pre_body_prose=True,
                    relax_prose_layout_gaps=True,
                    unwrap_bullet_continuations=True,
                    is_checkbox_answer_line=is_checkbox_answer_line,
                    is_page_boundary_line=is_page_marker_line,
                    is_structural_line=is_cover_layout_line,
                    is_table_bridge_line=is_financial_table_bridge_line,
                    is_table_tail_line=is_financial_table_tail_line,
                ),
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
                    line=map_line(body_start.line)
                    if body_start.line is not None
                    else None,
                    heading_line=map_line(body_start.heading_line)
                    if body_start.heading_line is not None
                    else None,
                    first_unit_line=map_line(body_start.first_unit_line)
                    if body_start.first_unit_line is not None
                    else None,
                )
            reflow_identity, reflow_line_count = _stage_metadata(text)
            stage_trace.append(
                {
                    "stage": "after_reflow",
                    "text_identity": reflow_identity,
                    "representation": representation,
                    "line_count": reflow_line_count,
                    "char_count": len(text),
                }
            )
        if body_start is not None and body_start.first_unit_line is not None:
            closing_span = find_closing_span(
                text, search_from=body_start.first_unit_line + 1
            )
        return NormalizationResult(
            text=text.strip(),
            cover_boundary=boundary,
            body_start=body_start,
            toc_span=toc_span,
            closing_span=closing_span,
            reflow=reflow_result,
            page_analysis=page_analysis,
            page_artifacts=build_page_artifact_metadata(
                page_artifact_policy,
                source_identity,
                artifact_templates,
                artifact_records,
            ),
            table_geometries=table_geometries,
            checkmark_inference=checkmark_inference,
            stage_trace=tuple(stage_trace),
        )


__all__ = ["DeepNormalizer", "NormalizationResult"]
