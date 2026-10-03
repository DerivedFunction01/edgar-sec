"""Conservative closing-region detection: signature blocks and exhibit indexes. A
missed region leaves body prose untouched; a false one can suppress body
normalization. Every signal needs an exact standalone structural line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.document.page_markers.signatures import (
    RE_CONFORMED_SIGNATURE,
)
from edgar_sec.engine.forms.cover.models import BoundaryEvidence
from edgar_sec.engine.tables.toc.patterns import (
    RE_PAGE_SUFFIX,
    RE_TOC_LEADER,
    is_toc_row,
)

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
    """The first closing-region line at or after `search_from`, which must be past the
    validated body start. None means no closing region; leave the tail as body text.
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
        # Any dot-leader row with a page suffix is TOC layout, including dotted
        # "SIGNATURES ... 60" rows that carry no Part/Item reference.
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
