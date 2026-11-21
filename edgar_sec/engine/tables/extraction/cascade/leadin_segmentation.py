"""Lead-in segmentation: a table's lead-in read from its own
section only — the segment from its last heading line on — and
the title chunks taken from that segment."""

from __future__ import annotations

import re

from edgar_sec.foundation.text.dates import MONTH_ALIASES, MONTH_NAMES

_TITLE_SPLIT = re.compile(r"\s*\|\s*|\n")
_SEGMENT_HEADING_MAX_CHARS = 90
_SEGMENT_HEADING_MAX_WORDS = 12
_PERIOD_LABEL_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "date",
        "dates",
        "ended",
        "ending",
        "fiscal",
        "for",
        "from",
        "month",
        "months",
        "of",
        "period",
        "quarter",
        "quarters",
        "the",
        "to",
        "transition",
        "year",
        "years",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
    }
    | set(MONTH_NAMES)
    | {alias.rstrip(".") for group in MONTH_ALIASES for alias in group}
)


def _is_segment_heading(line: str) -> bool:
    """A standalone heading line: short, unpunctuated, not furniture."""
    stripped = line.strip()
    if not 3 <= len(stripped) <= _SEGMENT_HEADING_MAX_CHARS:
        return False
    if stripped[-1] in ".:;!?" or ". " in stripped:
        return False
    if not (stripped[0].isupper() or stripped[0].isdigit()):
        return False
    words = stripped.split()
    if len(words) > _SEGMENT_HEADING_MAX_WORDS:
        return False
    if sum(ch.isalpha() for ch in stripped) < 3:
        return False
    if len(words) < 2 and not stripped.isupper():
        return False
    lowered = stripped.lower()
    if lowered.startswith("notes to") and "financial statements" in lowered:
        return False
    if lowered.strip(" —–-") in ("table of contents", "signatures"):
        return False
    if lowered.startswith("united states securities and exchange commission"):
        return False
    tokens = [word.strip(".,()").lower() for word in words]
    return not all(
        not token or token in _PERIOD_LABEL_WORDS or token.rstrip(",").isdigit()
        for token in tokens
    )


def leadin_segment(prose_before: str) -> str:
    """The lead-in from its last heading line on: its own section only.
    A lead-in spanning a preceding section carries that section's
    framing as evidence. No heading line: the lead-in unchanged."""
    text = prose_before or ""
    start = 0
    offset = 0
    for line in text.split("\n"):
        if _is_segment_heading(line):
            start = offset
        offset += len(line) + 1
    return text[start:] if start else text


def lead_title_text(prose_before: str) -> str:
    """The lead-in's title segments: its first two framing chunks."""
    segments = []
    for chunk in _TITLE_SPLIT.split(leadin_segment(prose_before)):
        stripped = chunk.strip()
        if stripped:
            segments.append(stripped)
        if len(segments) >= 3:
            break
    return " ".join(segments[:2])
