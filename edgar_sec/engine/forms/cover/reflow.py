"""Cover-specific policies supplied to the generic ASCII reflow engine.

Guards structured cover metadata (registrant name, jurisdiction, address, IRS,
12b securities, checkboxes) so narrative front-matter prose can safely unwrap
without mangling tabular metadata layouts.
"""

from __future__ import annotations

import re
from functools import lru_cache

from edgar_sec.domain.forms.checkmarks import CHECKMARK_MARK_RE
from edgar_sec.domain.forms.vocabulary import (
    ADDRESS_RE,
    COMMISSION_FILE_RE,
    IRS_EIN_RE,
    REGISTRANT_NAME_RE,
    SECURITIES_12B_RE,
    STATE_INCORPORATION_RE,
    TELEPHONE_RE,
    ZIP_RE,
)
from edgar_sec.engine.document.page_markers import is_page_marker_line
from edgar_sec.engine.forms.checkmarks._yesno import YES_NO_LINE_RE
from edgar_sec.engine.forms.cover.boundary import RE_TOC_HEADING
from edgar_sec.engine.forms.cover.structure import is_exact_heading
from edgar_sec.foundation.regex.builder import build_alternation

_FORM_PATTERN_WORDS = build_alternation(
    ["10-K", "10-Q", "8-K", "20-F", "40-F", "FORM"],
    auto_escape=True,
)
_FORM_PATTERN = re.compile(rf"\b(?:{_FORM_PATTERN_WORDS})\b", re.IGNORECASE)

_COVER_PATTERNS = (
    REGISTRANT_NAME_RE,
    STATE_INCORPORATION_RE,
    ADDRESS_RE,
    COMMISSION_FILE_RE,
    SECURITIES_12B_RE,
    IRS_EIN_RE,
    ZIP_RE,
    TELEPHONE_RE,
)


def is_checkbox_answer_line(line: str) -> bool:
    """Return whether a line has Yes/No grammar and an explicit mark."""
    return bool(YES_NO_LINE_RE.search(line) and CHECKMARK_MARK_RE.search(line))


@lru_cache(maxsize=16384)
def is_cover_layout_line(line: str) -> bool:
    """Return whether a line is a standalone cover/layout structure.

    The predicate is a pure function of the line text and runs regex searches
    per call; the reflow engine invokes it for every line in several passes,
    so results are memoized per line string.
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
