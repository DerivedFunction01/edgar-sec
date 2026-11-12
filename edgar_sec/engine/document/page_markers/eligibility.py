"""Line eligibility for furniture observation.
A line carrying content, structure, or a title shape is refused; only plain repeated banner text is admitted as a furniture candidate.
"""

from __future__ import annotations

import re

from .candidates import looks_like_prose
from .content_lines import is_content_line, is_date_line, is_rule_line
from .observations import _ALPHA_WORD_RE, _STANDALONE_TAG_RE, is_table_tag
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE, RE_FULL_DATE

_ITEM_HEADING_ALT = build_alternation(
    (
        r"item\s+[0-9a-z]+[.:]?",
        r"\(?[0-9]{1,2}\s*[\.\):]?",
    ),
    auto_escape=False,
    compact=True,
)
_ITEM_HEADING_RE = re.compile(rf"(?i)^\s*(?:{_ITEM_HEADING_ALT})\s+[a-z]")
_NOTE_CAPTION_RE = re.compile(r"(?i)^\s*note\s+\d{1,3}(?:\s*[\.\):\-]\s*|\s+)[a-z]")
_FORM_PREFIX_RE = re.compile(r"(?i)^\s*form\s+")
_BARE_ITEM_LABEL_RE = re.compile(r"(?i)^\(\s*[a-z0-9]{1,3}\s*\)$")
_RE_BARE_PERCENT = re.compile(r"^[+-]?\d+(?:\.\d+)?%$")
_RE_CHECKBOX_LINE = re.compile(r"\[[ xX_]\]")
_LONE_INITIAL_RE = re.compile(r"^[A-Za-z]\.?$")
_CONTINUATION_RE = re.compile(r"\(\s*(?:continued|cont\.)\s*\)", re.IGNORECASE)


def _is_form_caption(stripped: str) -> bool:
    """Return whether the line is a form caption: "Form" plus its numeric designation.
    The designation's shape is the governed numeric-date pattern, not a private one.
    """
    return bool(_FORM_PREFIX_RE.match(stripped) and NUMERIC_DATE_RE.search(stripped))


def _is_continuation_title(stripped: str) -> bool:
    """Return whether the line is a section-title continuation, not a running head.
    A "(continued)" marker on a multi-word line names the section it continues; the line is the section's title at its content position, however often the section spans pages.
    """
    if not _CONTINUATION_RE.search(stripped):
        return False
    return sum(1 for word in stripped.split() if _ALPHA_WORD_RE.search(word)) >= 2


def _is_dated_title_line(stripped: str) -> bool:
    """Return whether the line is a title carrying a full date, not a date line.
    The shape is a title-case title, a dash, and a full date at the line's end ("... Prospectus – April 27, 2015"); a period banner ("FOR THE YEAR END DECEMBER 31, 2025") has no dash and stays furniture.
    """
    match = RE_FULL_DATE.search(stripped)
    if match is None or stripped[match.end() :].strip(" ,"):
        return False
    head = stripped[: match.start()].rstrip()
    if not head.endswith(("–", "—", "-")):
        return False
    words = head.rstrip("–—-").split()
    title_words = sum(1 for word in words if word[:1].isupper() and not word.isupper())
    return len(words) >= 4 and title_words >= 2


def eligible_line(
    line: str,
    toc_lines: set[int],
    line_index: int,
    unit_kind: str | None,
    *,
    allow_table: bool,
) -> bool:
    """Return whether a candidate line may become a furniture observation.
    In-table and contents lines repeat because their container does, so they are refused unless the caller admits table furniture. A bare table tag is structure, never furniture text: a table is considered only as a whole block.
    """
    stripped = line.strip()
    if not stripped or line_index in toc_lines:
        return False
    if is_table_tag(stripped):
        return False
    if _STANDALONE_TAG_RE.match(stripped):
        return False
    if unit_kind == "table" and not allow_table:
        return False
    if looks_like_prose(stripped):
        return False
    if is_content_line(stripped):
        return False
    if is_date_line(stripped):
        return False
    if _LONE_INITIAL_RE.match(stripped):
        return False
    if _is_continuation_title(stripped):
        return False
    if _is_dated_title_line(stripped):
        return False
    if _is_form_caption(stripped):
        return False
    if _BARE_ITEM_LABEL_RE.match(stripped):
        return False
    if is_rule_line(stripped):
        return False
    if _NOTE_CAPTION_RE.match(stripped):
        return False
    if _ITEM_HEADING_RE.search(stripped):
        return False
    if _RE_BARE_PERCENT.fullmatch(stripped):
        return False
    if _RE_CHECKBOX_LINE.search(stripped):
        return False
    return not len(stripped) > 140


__all__ = [
    "eligible_line",
]
