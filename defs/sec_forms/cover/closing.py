"""Conservative closing-region detection: signature blocks and exhibit indexes.

The closing region is the tail of a filing after substantive body content:
signature pages, consent/parent-guardian certifications, and exhibit indexes.
Detection is deliberately conservative — a missed closing region leaves
ordinary body prose untouched, while a false closing start can suppress body
normalization. All signals therefore require exact, standalone structural
lines and the detector never reports a span inside a TOC or before the body.

This module is form-neutral. Form-specific item taxonomies (for example the
8-K ``ITEM 9.01`` exhibit list) stay with the owning form; this detector only
recognizes representation-level closing signals shared by all filings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from defs.sec_forms.cover.models import BoundaryEvidence
from defs.sec_forms.cover.toc import RE_TOC_LEADER, is_toc_row
from defs.sec_forms.page_markers import RE_PAGE_SUFFIX
from defs.text.patterns import RE_CONFORMED_SIGNATURE

__all__ = ["ClosingSpan", "find_closing_span"]

# Exact standalone closing headings. ``SIGNATURES`` commonly appears bare or
# followed on the same line by "Pursuant to the requirements of ...".
_RE_SIGNATURE_HEADING = re.compile(r"^SIGNATURES?\b[ \t]*.{0,120}$")
# Conformed ``/s/`` signature lines share the canonical text-level shape.
_RE_SLASH_S = RE_CONFORMED_SIGNATURE
# Exhibit index headings; must be standalone or a short label line.
_RE_EXHIBIT_HEADING = re.compile(r"^EXHIBITS?\b(?:\s+INDEX)?[.:]?\s*$")

_SIGNATURE_CONFIDENCE = 0.9
_SLASH_S_CONFIDENCE = 0.85
_EXHIBIT_CONFIDENCE = 0.7

_MAX_SCAN_LINES = 1500


@dataclass(frozen=True, slots=True)
class ClosingSpan:
    """Conservative, inclusive start of the closing region."""

    start_line: int
    kind: str  # "signatures" | "exhibit_index"
    confidence: float
    evidence: tuple[BoundaryEvidence, ...] = ()
    approximate: bool = True


def _heading_evidence(name: str, line: int, details: str) -> BoundaryEvidence:
    return BoundaryEvidence(name=name, strength=1.0, line=line, details=details)


def find_closing_span(
    text: str,
    *,
    search_from: int = 0,
) -> ClosingSpan | None:
    """Locate the first reliable closing-region line at or after ``search_from``.

    Returns ``None`` when no exact signature or exhibit-index signal exists;
    callers must treat an absent result as "no closing region detected" and
    leave the trailing content as ordinary body text.

    ``search_from`` should be the first line after validated body content
    (for example ``body_start.first_unit_line``); the detector never scans
    before it, so TOC rows and cover signature labels are out of scope.
    """
    if not text:
        return None
    lines = text.splitlines()
    search_from = max(search_from, 0)

    for index in range(search_from, min(len(lines), search_from + _MAX_SCAN_LINES)):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            continue
        if is_toc_row(line):
            continue
        # Any dot-leader row with a trailing page suffix is TOC layout,
        # including dotted ``SIGNATURES ... 60`` rows that lack a Part/Item
        # reference and therefore escape ``is_toc_row``.
        if RE_TOC_LEADER.search(stripped) and RE_PAGE_SUFFIX.search(stripped):
            continue

        if _RE_SIGNATURE_HEADING.match(stripped) and stripped.upper() == stripped:
            return ClosingSpan(
                start_line=index,
                kind="signatures",
                confidence=_SIGNATURE_CONFIDENCE,
                evidence=(
                    _heading_evidence("signatures_heading", index, stripped[:120]),
                ),
            )
        if _RE_SLASH_S.match(line):
            return ClosingSpan(
                start_line=index,
                kind="signatures",
                confidence=_SLASH_S_CONFIDENCE,
                evidence=(
                    _heading_evidence("slash_s_signature", index, stripped[:120]),
                ),
            )
        if _RE_EXHIBIT_HEADING.match(stripped):
            return ClosingSpan(
                start_line=index,
                kind="exhibit_index",
                confidence=_EXHIBIT_CONFIDENCE,
                evidence=(
                    _heading_evidence("exhibit_index_heading", index, stripped[:120]),
                ),
            )
    return None
