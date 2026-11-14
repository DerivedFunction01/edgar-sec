"""Residue families: content evidence beyond the note title.

Segment, commitments and related-party tables earn their claim
from content in the grid, not from their note's title alone.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.competition import GeometryText
from edgar_sec.engine.tables.extraction.normalize import normalize_text

PROV_STEP3_RESIDUE = "improvement-step3:residue-content"

CONTENT_GATED_FAMILIES = (
    "segment_reporting",
    "commitments_contingencies",
    "related_party",
)
CONTENT_TERMS: dict[str, tuple[str, ...]] = {
    "segment_reporting": (
        "operating segments",
        "segment revenue",
        "segment profit",
        "segment income",
        "segment assets",
        "reportable segments",
        "chief operating decision",
        "total segment",
    ),
    "commitments_contingencies": (
        "loss contingency",
        "loss contingencies",
        "litigation",
        "legal proceedings",
        "guarantee",
        "guarantees",
        "letters of credit",
        "purchase commitments",
        "purchase obligations",
        "environmental remediation",
        "indemnification",
    ),
    "related_party": (
        "related party transactions",
        "related-party transactions",
        "transactions with related parties",
        "amounts due from related parties",
        "amounts due to related parties",
        "due from related parties",
        "due to related parties",
        "affiliated companies",
        "related party receivables",
        "related party payables",
    ),
}
SEGMENT_MEASURES = (
    "revenue",
    "revenues",
    "net sales",
    "profit",
    "income",
    "assets",
    "operating income",
)
CORROBORATION_MINIMUM = 2
SEGMENT_TERM_MINIMUM = 1


def _text(geometry: GeometryText) -> str:
    parts = (
        geometry.stub_text,
        normalize_text(geometry.caption),
        normalize_text(geometry.leadin),
    )
    return " ".join(part for part in parts if part)


def content_terms_present(family: str, geometry: GeometryText) -> tuple[str, ...]:
    """The family's distinct content terms present in the grid text."""
    text = _text(geometry)
    return tuple(term for term in CONTENT_TERMS.get(family, ()) if term in text)


def content_score(family: str, geometry: GeometryText) -> int:
    """Distinct content terms present; the title never scores."""
    return len(content_terms_present(family, geometry))


def segment_grid(geometry: GeometryText) -> bool:
    """A by-segment measure grid: segment terms plus measure rows."""
    if content_score("segment_reporting", geometry) < SEGMENT_TERM_MINIMUM:
        return False
    text = _text(geometry)
    return any(measure in text for measure in SEGMENT_MEASURES)


def corroborates(family: str, geometry: GeometryText) -> bool:
    """Content corroboration for a note-title claim on this family."""
    if family == "segment_reporting":
        return segment_grid(geometry)
    minimum = CORROBORATION_MINIMUM
    return content_score(family, geometry) >= minimum
