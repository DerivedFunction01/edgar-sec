"""Normalization result models and stage tracing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from defs.sec_forms.cover.models import CoverBoundary


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
    page_artifacts: dict[str, Any] | None = None
    table_geometries: tuple = ()
    checkmark_inference: object | None = None
    stage_trace: tuple[dict[str, Any], ...] = ()


__all__ = ["NormalizationResult"]
