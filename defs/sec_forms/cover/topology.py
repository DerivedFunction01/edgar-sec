"""Document topology resolution across Cover, TOC, and Body zones."""

from __future__ import annotations

from defs.sec_forms.cover.body_start import find_body_start
from defs.sec_forms.cover.boundary import (
    CoverBoundary,
    CoverBoundaryPolicy,
    find_cover_boundary,
)
from defs.sec_forms.cover.cover_start import find_cover_start
from defs.sec_forms.cover.models import (
    BoundaryEvidence,
    BoundaryInput,
    DocumentTopology,
)
from defs.sec_forms.cover.toc import find_toc_span


def resolve_document_topology(
    boundary_input: BoundaryInput | str,
    policy: CoverBoundaryPolicy | None = None,
    *,
    cover_evidence: tuple[str, ...] | None = None,
    body_evidence: tuple[str, ...] | None = None,
    body_evidence_pack: object | None = None,
    derived_taxonomy: dict | None = None,
) -> DocumentTopology:
    """Resolve the complete 4-zone document partition (Cover, TOC, Body)."""
    raw_text = (
        boundary_input.text
        if isinstance(boundary_input, BoundaryInput)
        else boundary_input
    )
    cover_start = find_cover_start(
        boundary_input,
        policy=policy,
        cover_evidence=cover_evidence,
    )
    cover_boundary: CoverBoundary = find_cover_boundary(
        boundary_input,
        policy,
        cover_evidence=cover_evidence,
        body_evidence=body_evidence,
    )

    toc_span = find_toc_span(
        raw_text,
        start_line=cover_start.start_line or 0,
        derived_taxonomy=derived_taxonomy,
    )

    evidence: list[BoundaryEvidence] = list(cover_boundary.evidence)

    if toc_span is not None:
        cover_end = toc_span.start_line
        toc_start = toc_span.start_line
        toc_end = toc_span.end_line
        body_start = toc_span.end_line
        method = f"toc_transition_{toc_span.method}"
        confidence = max(cover_boundary.confidence, toc_span.confidence)
        evidence.append(
            BoundaryEvidence(
                name=f"toc_span_{toc_span.method}",
                strength=toc_span.confidence,
                line=toc_span.start_line,
                details=f"TOC from line {toc_span.start_line} to {toc_span.end_line}",
            )
        )
    else:
        cover_end = cover_boundary.end_line
        toc_start = None
        toc_end = None
        body_start = cover_boundary.end_line
        method = f"direct_{cover_boundary.method.value}"
        confidence = cover_boundary.confidence

    if body_evidence_pack is not None:
        detected = find_body_start(
            raw_text,
            cover_end=cover_boundary.end_line,
            toc_end=toc_end,
            evidence=body_evidence_pack,
            toc_span=toc_span,
        )
        if detected.line is not None:
            body_start = detected.line
            method = f"body_start_{detected.anchor_type}"
            confidence = detected.confidence
            evidence.append(
                BoundaryEvidence(
                    name="body_start_detected",
                    strength=detected.confidence,
                    line=detected.line,
                    details=detected.reason,
                )
            )
    elif cover_end is None and body_start is None:
        body_start = _fallback_body_root(raw_text)
        if body_start is not None:
            method = "direct_opening_body_root"
            confidence = 0.75

    return DocumentTopology(
        cover_start=cover_start.start_line,
        cover_end=cover_end,
        toc_start=toc_start,
        toc_end=toc_end,
        body_start=body_start,
        confidence=confidence,
        method=method,
        evidence=tuple(evidence),
    )


def _fallback_body_root(raw_text: str) -> int | None:
    """Last-resort scan for an opening body root without an evidence pack.

    Only used when no cover boundary and no evidence pack are available.
    Prefers PART I over a bare ITEM 1 to reduce TOC false positives.
    """
    lines = raw_text.splitlines()
    first_part: int | None = None
    for idx in range(min(10, len(lines))):
        line_str = lines[idx].strip().upper()
        if line_str in ("PART I", "PART 1"):
            first_part = idx
            break
        if first_part is None and line_str.startswith("ITEM 1"):
            first_part = idx
    return first_part


__all__ = ["resolve_document_topology"]
