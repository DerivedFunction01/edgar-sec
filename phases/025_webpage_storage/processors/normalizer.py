"""Deep document normalization and form-aware SEC content standardization."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from defs.sec_forms.cover import (
    BoundaryInput,
    CoverBoundary,
    find_body_start,
    find_closing_span,
    find_cover_boundary_for_profile,
    find_toc_span,
    get_profile,
    heal_cover_text,
)
from defs.sec_forms.page_markers import (
    PageArtifactPolicy,
    analyze_page_markers,
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
    """

    text: str
    cover_boundary: CoverBoundary
    body_start: object | None = None
    toc_span: object | None = None
    closing_span: object | None = None
    reflow: object | None = None
    page_analysis: object | None = None
    page_artifacts: dict | None = None


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
        # One representation decision for the whole normalize pass so every
        # boundary call shares the same coordinate-frame declaration.
        representation = preprocessed.representation or (
            "html" if preprocessed.has_html_tags else "ascii"
        )
        is_html = representation == "html" or preprocessed.has_html_tags
        text = preprocessed.cleaned_text
        page_analysis = None

        source_identity = hashlib.sha256(text.encode("utf-8")).hexdigest()
        artifact_templates: dict[str, dict] = {}
        artifact_records: list[tuple[int, object]] = []
        next_artifact_id = 1
        if is_html:
            first_html_id = next_artifact_id
            (
                text,
                page_analysis,
                html_artifacts,
                html_templates,
                next_artifact_id,
            ) = apply_html_policy(
                text,
                page_analysis,
                page_artifact_policy,
                first_id=first_html_id,
            )
            artifact_templates.update(html_templates)
            artifact_records.extend(
                zip(range(first_html_id, next_artifact_id), html_artifacts)
            )
        else:
            first_ascii_id = next_artifact_id
            (
                text,
                page_analysis,
                ascii_artifacts,
                ascii_templates,
                next_artifact_id,
            ) = apply_text_policy(
                text,
                page_analysis,
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

        boundary = find_cover_boundary_for_profile(
            BoundaryInput(
                text,
                representation=representation,
                page_analysis=page_analysis,
            ),
            profile,
        )

        healed_text, cover_changed = heal_cover_text(
            text,
            boundary,
            tuple(profile.healing_rules),
        )
        if cover_changed:
            text = healed_text
            # Healing can merge lines, so line-based consumers need a fresh
            # analysis and boundary in the new coordinate frame.
            page_analysis = analyze_page_markers(text, representation="ascii")
            boundary = find_cover_boundary_for_profile(
                BoundaryInput(
                    text,
                    representation=representation,
                    page_analysis=page_analysis,
                ),
                profile,
            )

        # Form-specific heading standardization
        text = form_normalizer.normalize_headers(text, metadata)

        # 5. Final whitespace cleanup
        text = normalize_final_text_whitespace(text)
        body_start = None
        toc_span = None
        closing_span = None
        reflow_result = None
        if profile.boundary is not None and profile.body_evidence is not None:
            # Body-start analysis runs on the final normalized text; resolve
            # the TOC span on the same representation so the search lower
            # bound and TOC ineligibility use consistent line coordinates.
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
        # ASCII-only span/action pass. HTML keeps its semantic/DOM path and is
        # never hard-wrapped. Everything before the validated body anchor is
        # preserved; without an anchor no reflow happens at all.
        if (
            not is_html
            and body_start is not None
            and body_start.first_unit_line is not None
        ):
            reflow_result = reflow_ascii(
                text,
                body_start_line=body_start.first_unit_line,
                page_analysis=page_analysis,
            )
            text = reflow_result.text
        # Closing-region detection only scans after a validated body anchor;
        # without one the trailing content stays ordinary body text rather
        # than risking a premature closing cut. The reflow pass never shifts
        # lines at or before ``first_unit_line``, so the anchor remains valid
        # in the reflowed frame.
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
        )


__all__ = ["DeepNormalizer", "NormalizationResult"]
