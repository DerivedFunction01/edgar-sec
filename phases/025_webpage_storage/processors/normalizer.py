"""Deep document normalization and form-aware SEC content standardization."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from defs.sec_forms.cover import (
    BoundaryInput,
    CoverBoundary,
    apply_cover_checkmark_decisions,
    find_body_start,
    find_closing_span,
    find_cover_boundary_for_profile,
    find_toc_span,
    get_profile,
    heal_cover_text,
    infer_cover_checkmarks,
    update_table_geometries,
)
from defs.sec_forms.cover.checkmark_rewrite import _has_labeled_checkmark_candidates
from defs.sec_forms.page_markers import (
    PageArtifactPolicy,
    apply_html_policy,
    apply_text_policy,
    build_page_artifact_metadata,
)
from defs.text import normalize_final_text_whitespace
from defs.text.reflow import reflow_ascii

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

        source_identity = hashlib.sha256(text.encode("utf-8")).hexdigest()
        stage_trace.append(
            {
                "stage": "preprocessed",
                "text_identity": source_identity,
                "representation": representation,
                "line_count": len(text.splitlines()),
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
            stage_trace.append(
                {
                    "stage": "page_policy_input",
                    "text_identity": source_identity,
                    "representation": representation,
                    "line_count": len(text.splitlines()),
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

        stage_trace.append(
            {
                "stage": "page_policy_output",
                "text_identity": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "representation": representation,
                "line_count": len(text.splitlines()),
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

        checkmark_inference = infer_cover_checkmarks(
            text,
            boundary,
            family=profile.family,
            table_geometries=table_geometries,
            schema=profile.checkbox_schema,
        )
        if checkmark_inference.decisions or _has_labeled_checkmark_candidates(
            checkmark_inference.candidates
        ):
            table_geometries = update_table_geometries(
                table_geometries,
                checkmark_inference,
            )
            text, checkmark_changed = apply_cover_checkmark_decisions(
                text,
                checkmark_inference,
            )
            if checkmark_changed:
                stage_trace.append(
                    {
                        "stage": "after_checkmark_rewrite",
                        "text_identity": hashlib.sha256(
                            text.encode("utf-8")
                        ).hexdigest(),
                        "representation": representation,
                        "line_count": len(text.splitlines()),
                        "char_count": len(text),
                    }
                )

        healed_text, cover_changed = heal_cover_text(
            text,
            boundary,
            tuple(profile.healing_rules),
        )
        if cover_changed:
            text = healed_text
            stage_trace.append(
                {
                    "stage": "after_cover_healing",
                    "text_identity": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "representation": representation,
                    "line_count": len(text.splitlines()),
                    "char_count": len(text),
                }
            )

        text = form_normalizer.normalize_headers(text, metadata)
        stage_trace.append(
            {
                "stage": "after_header_normalization",
                "text_identity": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "representation": representation,
                "line_count": len(text.splitlines()),
                "char_count": len(text),
            }
        )

        text = normalize_final_text_whitespace(text)
        stage_trace.append(
            {
                "stage": "after_final_whitespace",
                "text_identity": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "representation": representation,
                "line_count": len(text.splitlines()),
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
        if (
            not is_html
            and body_start is not None
            and body_start.first_unit_line is not None
        ):
            stage_trace.append(
                {
                    "stage": "before_reflow",
                    "text_identity": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "representation": representation,
                    "line_count": len(text.splitlines()),
                    "char_count": len(text),
                }
            )
            reflow_result = reflow_ascii(
                text,
                body_start_line=body_start.first_unit_line,
                page_analysis=page_analysis,
            )
            text = reflow_result.text
            stage_trace.append(
                {
                    "stage": "after_reflow",
                    "text_identity": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "representation": representation,
                    "line_count": len(text.splitlines()),
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
