"""Residue families: content evidence beyond the note title.

Segment, commitments and related-party tables earn their claim
from content in the grid, not from their note's title alone.
"""

from __future__ import annotations

import re

from edgar_sec.engine.tables.extraction.competition import GeometryText
from edgar_sec.engine.tables.extraction.normalize import normalize_text

CONTENT_GATED_FAMILIES = (
    "segment_reporting",
    "commitments_contingencies",
    "related_party",
)
CONTENT_TERMS: dict[str, tuple[str, ...]] = {
    "segment_reporting": (
        "operating segments",
        "operating segment",
        "reportable segments",
        "reportable segment",
        "business segments",
        "business segment",
        "segment revenue",
        "segment profit",
        "segment income",
        "segment assets",
        "segment operating income",
        "segment net sales",
        "segment results",
        "segment information",
        "segment operations",
        "segment reporting",
        "total segment",
        "chief operating decision",
        "intersegment",
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
        "commitments to extend credit",
        "unused lines of credit",
        "standby bond purchase",
        "unfunded commitments",
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
    "sales",
    "profit",
    "income",
    "assets",
    "operating income",
    "operating loss",
    "depreciation",
    "amortization",
    "capital expenditures",
    "expenses",
    "gross margin",
    "ebitda",
)
SEGMENT_RECONCILIATION_MARKERS = (
    "corporate and other",
    "eliminations",
    "intersegment",
    "consolidated",
    "unallocated",
    "non-segment",
    "nonsegment",
    "corporate",
)
CORROBORATION_MINIMUM = 2
SEGMENT_TERM_MINIMUM = 1

_SEGMENT_WORD = re.compile(r"\bsegments?\b")


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


def _segment_channels(geometry: GeometryText) -> tuple[str, str, str]:
    """Segment channels: full, grid (every cell, headers too), framing."""
    grid = " ".join(
        part
        for part in (
            geometry.stub_text,
            normalize_text(geometry.caption),
            normalize_text(geometry.grid_text),
        )
        if part
    )
    framing = " ".join(
        part
        for part in (
            normalize_text(geometry.caption),
            normalize_text(geometry.leadin),
        )
        if part
    )
    return " ".join((grid, framing)), grid, framing


def segment_terms_present(geometry: GeometryText) -> tuple[str, ...]:
    """The segment content terms present over the full grid text."""
    full, _, _ = _segment_channels(geometry)
    return tuple(term for term in CONTENT_TERMS["segment_reporting"] if term in full)


def segment_grid(geometry: GeometryText) -> bool:
    """A by-segment measure grid, admitted on any priced arm."""
    _, grid, framing = _segment_channels(geometry)
    measure_grid = any(measure in grid for measure in SEGMENT_MEASURES)
    measure_full = measure_grid or any(
        measure in framing for measure in SEGMENT_MEASURES
    )
    if not measure_full:
        return False
    if segment_terms_present(geometry) and measure_grid:
        return True
    if _SEGMENT_WORD.search(grid) and measure_grid:
        return True
    markers = {m for m in SEGMENT_RECONCILIATION_MARKERS if m in grid}
    if len(markers) >= 2 and "total" in grid and measure_grid:
        return True
    framed = _SEGMENT_WORD.search(framing) is not None
    if framed and measure_grid and "total" in grid:
        return True
    if framed and "disaggregat" in framing and measure_grid:
        return True
    return bool(framed and "geographic" in framing and "total" in grid)


def corroborates(family: str, geometry: GeometryText) -> bool:
    """Content corroboration for a note-title claim on this family."""
    if family == "segment_reporting":
        return segment_grid(geometry)
    minimum = CORROBORATION_MINIMUM
    return content_score(family, geometry) >= minimum
