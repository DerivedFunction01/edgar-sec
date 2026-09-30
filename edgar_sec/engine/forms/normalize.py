"""Central document normalization seam connecting raw bytes to normalized text.

This minimal reference implementation satisfies pipelines during the Phase 2.5
clean-slate re-landing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from edgar_sec.domain.forms.families import resolve_alias
from edgar_sec.engine.document.page_markers import PageMarkerAnalysis


class BoundaryMethod(StrEnum):
    """Signals identifying a cover boundary transition."""

    NONE = "none"
    TOC_TRANSITION = "toc_transition"
    INCORPORATED_REFERENCE = "incorporated_reference"
    PART_FALLBACK = "part_fallback"
    ITEM_FALLBACK = "item_fallback"
    PAGE_MARKERS = "page_markers"


@dataclass(frozen=True, slots=True)
class CoverBoundary:
    """Delimits the cover page span within document lines."""

    start_line: int = 0
    end_line: int = 0
    method: BoundaryMethod = BoundaryMethod.NONE
    confidence: float = 0.0
    approximate: bool = False


@dataclass(frozen=True, slots=True)
class BodyStart:
    """Location and anchor details for the body prose start."""

    line: int = 0
    heading_line: int | None = None
    first_unit_line: int | None = None
    anchor_type: str | None = None
    confidence: float = 1.0
    delayed: bool = False
    rejection_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClosingSpan:
    """Location and classification of document closing signatures and exhibits."""

    start_line: int
    end_line: int
    kind: str
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ReflowDecision:
    """Record of an individual block reflow action."""

    action: str
    line_count: int = 0


@dataclass(frozen=True, slots=True)
class ReflowSummary:
    """Summary of prose reflow decisions across a document."""

    decisions: list[ReflowDecision] = field(default_factory=list)


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
    closing_span: ClosingSpan | None = None
    page_analysis: PageMarkerAnalysis | None = None
    reflow: ReflowSummary | None = None
    stage_trace: list[str] = field(default_factory=list)


def normalize_document(
    raw_bytes: bytes,
    *,
    form: str | None = None,
) -> NormalizationResult:
    """Baseline document normalizer satisfying the pipeline contract.

    Decodes raw payload using standard multi-tier fallbacks and returns a
    structured NormalizationResult.
    """
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw_bytes.decode("latin-1", errors="replace")

    canonical_family = resolve_alias(form)
    family = canonical_family or (form.upper().strip() if form else "GENERIC")

    is_html = (
        b"<html" in raw_bytes.lower() or b"<HTML" in raw_bytes or b"<BODY" in raw_bytes
    )
    representation = "html" if is_html else "ascii"

    boundary = CoverBoundary(
        start_line=0,
        end_line=0,
        method=BoundaryMethod.NONE,
        confidence=0.0,
    )

    return NormalizationResult(
        text=text,
        family=family,
        representation=representation,
        cover_boundary=boundary,
        cover_boundary_detected_line=0,
        cover_start_detected_line=0,
        stage_trace=["decode"],
    )


__all__ = [
    "BodyStart",
    "BoundaryMethod",
    "ClosingSpan",
    "CoverBoundary",
    "NormalizationResult",
    "ReflowDecision",
    "ReflowSummary",
    "normalize_document",
]
