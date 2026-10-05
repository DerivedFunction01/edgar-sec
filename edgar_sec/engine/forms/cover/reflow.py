"""Cover-specific policies supplied to the generic ASCII reflow engine: one predicate
refuses to unwrap a Yes/No answer row into prose, the other refuses to unwrap a
standalone cover layout structure.
"""

from __future__ import annotations

from functools import lru_cache

from edgar_sec.domain.forms.common.checkmarks import CHECKMARK_MARK_RE
from edgar_sec.domain.forms.common.vocabulary import (
    _FORM_PATTERN,
    ADDRESS_RE,
    COMMISSION_FILE_RE,
    REGISTRANT_NAME_RE,
    SECURITIES_12B_RE,
    STATE_INCORPORATION_RE,
)
from edgar_sec.engine.document.page_markers.detector import is_page_marker_line
from edgar_sec.engine.forms.cover.checkmarks.yes_no_pairs import YES_NO_LINE_RE
from edgar_sec.engine.forms.cover.structure import is_exact_heading
from edgar_sec.engine.forms.cover.toc.patterns import RE_TOC_HEADING


def is_checkbox_answer_line(line: str) -> bool:
    """Return whether a line has Yes/No grammar and an explicit mark."""
    return bool(YES_NO_LINE_RE.search(line) and CHECKMARK_MARK_RE.search(line))


_COVER_PATTERNS = (
    REGISTRANT_NAME_RE,
    STATE_INCORPORATION_RE,
    ADDRESS_RE,
    COMMISSION_FILE_RE,
    SECURITIES_12B_RE,
)


@lru_cache(maxsize=16384)
def is_cover_layout_line(line: str) -> bool:
    """Whether a line is a standalone cover/layout structure. The reflow engine calls
    this for every line in several passes, so results are memoized per line.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if is_exact_heading(line) or RE_TOC_HEADING.match(line):
        return True
    if len(stripped.split()) <= 4 and _FORM_PATTERN.search(stripped):
        return True
    for pattern in _COVER_PATTERNS:
        if pattern.search(line):
            return True
    return False


__all__ = [
    "is_checkbox_answer_line",
    "is_cover_layout_line",
    "is_page_marker_line",
]
