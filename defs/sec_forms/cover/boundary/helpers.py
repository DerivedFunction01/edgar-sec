"""Utility functions and constants for cover boundary detection."""

from __future__ import annotations

import re

# Maximum lines between a TOC heading and its first row for the heading to act
# as an incorporated-reference transition; mirrors the TOC span gap gate.
_TOC_TRANSITION_ROW_GAP = 10

_RE_TAGGED_TABLE_OPEN = re.compile(r"<TABLE\b", re.IGNORECASE)
_RE_TAGGED_TABLE_CLOSE = re.compile(r"</TABLE\s*>", re.IGNORECASE)

# Lines describing other sections (for example inside an incorporated-reference
# sentence) must not trigger the body-prose depth guard.
_REFERENCE_DESCRIPTION_MARKERS = ("incorporated", "portions of")
_QUOTED_SECTION_MARKERS = (
    'headings "',
    'heading "',
    "entitled",
    "titled",
    "sections of",
)


def _prev_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    for index in range(start_line, -1, -1):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def _is_proxy_reference_disclosure(line: str) -> bool:
    stripped = line.strip().lower()
    return bool(
        stripped.startswith(
            (
                "portions of",
                "the information required",
                "information required",
                "see part",
                "refer to",
            )
        )
    )


def _enabled(policy: object, signal: object) -> bool:
    return signal in policy.signals


def _line_offset(lines: list[str], line: int) -> int:
    return sum(len(value) + 1 for value in lines[:line])


def _line_at_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)
