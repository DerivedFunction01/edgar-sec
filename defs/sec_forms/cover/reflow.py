"""Cover-specific policies supplied to the generic ASCII reflow engine."""

from __future__ import annotations

from defs.sec_forms.cover.checkmark.yes_no_pairs import YES_NO_LINE_RE
from defs.sec_forms.cover.structure import is_exact_heading
from defs.sec_forms.cover.toc.patterns import RE_TOC_HEADING
from defs.sec_forms.page_markers import is_page_marker_line
from defs.sec_forms.vocabulary import (
    _FORM_PATTERN,
    ADDRESS_RE,
    COMMISSION_FILE_RE,
    REGISTRANT_NAME_RE,
    SECURITIES_12B_RE,
    STATE_INCORPORATION_RE,
)
from defs.text.checkmarks import CHECKMARK_MARK_RE


def is_checkbox_answer_line(line: str) -> bool:
    """Return whether a line has Yes/No grammar and an explicit mark."""
    return bool(YES_NO_LINE_RE.search(line) and CHECKMARK_MARK_RE.search(line))


def is_cover_layout_line(line: str) -> bool:
    """Return whether a line is a standalone cover/layout structure."""
    return bool(
        is_exact_heading(line)
        or RE_TOC_HEADING.match(line)
        or _FORM_PATTERN.search(line)
        or any(
            pattern.search(line)
            for pattern in (
                REGISTRANT_NAME_RE,
                STATE_INCORPORATION_RE,
                ADDRESS_RE,
                COMMISSION_FILE_RE,
                SECURITIES_12B_RE,
            )
        )
    )


__all__ = [
    "is_checkbox_answer_line",
    "is_cover_layout_line",
    "is_page_marker_line",
]
