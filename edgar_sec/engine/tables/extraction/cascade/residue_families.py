"""Residue families: content evidence beyond the note title.

Segment, commitments and related-party tables earn their claim
from content in the grid, not from their note's title alone.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from edgar_sec.domain.world.geography import place_terms
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.date_patterns import YEAR_TOKEN_SEARCH_RE
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.patterns import SCALE_PATTERNS
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text

if TYPE_CHECKING:
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        CompetitionResult,
    )

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


_PLACE_TERMS = place_terms()


def geographic_terms_present(geometry: GeometryText) -> tuple[str, ...]:
    """The world substrate's place terms present in the grid channel."""
    _, grid, _ = _segment_channels(geometry)
    return tuple(term for term in _PLACE_TERMS if term in grid)


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
    if framed and geographic_terms_present(geometry) and "total" in grid:
        return True
    return bool(framed and "geographic" in framing and "total" in grid)


_PERIOD_WORDS = (
    "ended",
    "months",
    "years",
    "quarter",
    "dollars",
    "except",
    "change",
)
_PERIOD_WORDS_RE = re.compile(
    rf"(?:{build_alternation(_PERIOD_WORDS, auto_escape=True)})"
)
_SCALE_HEADER_NAMES = (
    "thousands",
    "millions",
)
_SCALE_HEADER_RES = tuple(
    pattern for pattern, name in SCALE_PATTERNS if name in _SCALE_HEADER_NAMES
)


def _is_period_header(header: str) -> bool:
    """A header cell that dates or scales a column, not a partition."""
    return bool(
        YEAR_TOKEN_SEARCH_RE.search(header)
        or _PERIOD_WORDS_RE.search(header)
        or any(pattern.search(header) for pattern in _SCALE_HEADER_RES)
    )


def segment_header_partition(geometry: GeometryText) -> bool:
    """A total column among three or more non-period headers."""
    headers = [h.strip().lower() for h in geometry.headers if h.strip()]
    non_period = [h for h in headers if not _is_period_header(h)]
    total_col = any(
        h == "total" or h.startswith("total ") or "consolidated" in h
        for h in non_period
    )
    return total_col and len(non_period) >= 3


def segment_geographic_partition(geometry: GeometryText) -> bool:
    """Three or more geographic terms, closed by a total stub."""
    stubs = [s.strip().lower() for s in geometry.stubs]
    total_stub = any(
        s == "total" or s.startswith("total ") or s.startswith("total:") for s in stubs
    )
    return total_stub and len(geographic_terms_present(geometry)) >= 3


_NAME_PERIOD_WORDS = frozenset(
    {
        "quarter",
        "quarters",
        "month",
        "months",
        "year",
        "years",
        "period",
        "periods",
        "fiscal",
        "ended",
        "ending",
        "date",
        "dates",
        "q1",
        "q2",
        "q3",
        "q4",
        "annual",
        "interim",
        "three",
        "six",
        "nine",
        "twelve",
    }
)
# A candidate name dies if any token is a financial
# line-item word: segment names name businesses, not rows.
_NAME_LINE_ITEM_TOKENS = frozenset(
    {
        "revenue",
        "revenues",
        "income",
        "profit",
        "profits",
        "loss",
        "losses",
        "expenditure",
        "expenditures",
        "expense",
        "expenses",
        "assets",
        "liabilities",
        "cash",
        "flows",
        "earnings",
        "margin",
        "amortization",
        "depreciation",
        "taxes",
        "sales",
        "cost",
        "costs",
        "charges",
        "benefits",
    }
)
# A candidate name dies if any token is a unit/measure
# word: names name businesses, not scales. The scale words
# compose from their home in tables/patterns.
_NAME_UNIT_TOKENS = frozenset(
    {"in", "dollars", "usd"}
    | {name for _pattern, name in SCALE_PATTERNS if name != "hundreds"}
)
# A candidate name dies if every token is structural.
_NAME_STRUCTURAL_TOKENS = frozenset(
    {
        "total",
        "consolidated",
        "corporate",
        "eliminations",
        "elimination",
        "unallocated",
        "combined",
        "company",
        "parent",
        "other",
        "and",
        "the",
        "of",
        "segment",
        "segments",
        "reportable",
    }
)
_NAME_TOKEN_RE = re.compile(r"[^a-z0-9&']+")


def _name_form(text: str) -> str:
    """The caption-name channel's word form: lowercase words."""
    return " ".join(_NAME_TOKEN_RE.sub(" ", (text or "").lower()).split())


def _segment_name_candidate(cell: str) -> str | None:
    """A stub cell as a segment name, or None when it names none."""
    name = _name_form(cell)
    if not name:
        return None
    tokens = name.split()
    if not 2 <= len(tokens) <= 6:
        return None
    if any(token.isdigit() for token in tokens):
        return None
    if any(token in _NAME_PERIOD_WORDS for token in tokens):
        return None
    if any(token in _NAME_LINE_ITEM_TOKENS for token in tokens):
        return None
    if any(token in _NAME_UNIT_TOKENS for token in tokens):
        return None
    if all(token in _NAME_STRUCTURAL_TOKENS for token in tokens):
        return None
    if "total" in tokens or "consolidated" in tokens:
        return None
    return name


def segment_vocabulary(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    results: list[CompetitionResult] | tuple[CompetitionResult, ...],
) -> frozenset[str]:
    """Segment names from the filing's pre-seat segment tables' stubs."""
    names: set[str] = set()
    for geometry, result in zip(geometries, results, strict=True):
        if "segment_reporting" not in result.claims:
            continue
        if any(
            group.family == "segment_reporting" and group.state == "reach"
            for group in result.groups
        ):
            continue
        for stub in geometry.stubs:
            name = _segment_name_candidate(stub)
            if name:
                names.add(name)
    return frozenset(names)


_NAME_WORD_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")


def segment_caption_name(text: str, vocabulary: frozenset[str]) -> bool:
    """The caption carries one of the filing's own segment names."""
    caption = _name_form(text)
    if not caption or not vocabulary:
        return False
    for name in sorted(vocabulary, key=len, reverse=True):
        start = caption.find(name)
        while start >= 0:
            before = caption[start - 1] if start else ""
            after_at = start + len(name)
            after = caption[after_at] if after_at < len(caption) else ""
            if before not in _NAME_WORD_CHARS and after not in _NAME_WORD_CHARS:
                return True
            start = caption.find(name, start + 1)
    return False


def corroborates(family: str, geometry: GeometryText) -> bool:
    """Content corroboration for a note-title claim on this family."""
    if family == "segment_reporting":
        return segment_grid(geometry)
    minimum = CORROBORATION_MINIMUM
    return content_score(family, geometry) >= minimum
