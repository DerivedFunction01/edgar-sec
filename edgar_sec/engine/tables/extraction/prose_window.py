"""Prose-window grain: decisions the geometry alone cannot carry.

R-C4's filer-status grid sits in the prose around a checkbox
fragment, not in the fragment; this module reads that window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.competition import GeometryText
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.normalize import normalize_text

PROV_PROSE_WINDOW = "prose-window:filer_status"

WINDOW_LIMIT = 4000
_MARK_SPAN = 48
CHECKED_MARKS = ("☑", "☒", "⌧", "[x]", "(x)", "■")
UNCHECKED_MARKS = ("☐", "□", "[ ]", "( )")
FILER_CATEGORIES = (
    "large accelerated filer",
    "non-accelerated filer",
    "accelerated filer",
    "smaller reporting company",
    "emerging growth company",
)
_CATEGORY_RE = {
    category: re.compile(re.escape(category)) for category in FILER_CATEGORIES
}


def window_text(before: str, caption: str, after: str) -> str:
    """The bounded prose window framing one geometry, normalized."""
    head = (before or "")[-WINDOW_LIMIT // 2 :]
    tail = (after or "")[: WINDOW_LIMIT // 4]
    joined = " ".join(part for part in (head, caption or "", tail) if part)
    return normalize_text(joined)[:WINDOW_LIMIT]


def window_from_context(context: TableContext, caption: str = "") -> str:
    """The prose window around a context's geometry."""
    return window_text(context.prose_before, caption, context.prose_after)


@dataclass(frozen=True, slots=True)
class FilerStatusReading:
    """One filer-status block read at prose-window grain."""

    present: tuple[str, ...]
    marked: tuple[str, ...]
    grain: str = "prose_window"
    provenance: str = PROV_PROSE_WINDOW

    @property
    def decided(self) -> bool:
        """Decided when exactly one category carries the check."""
        return len(self.marked) == 1


def _is_marked(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - _MARK_SPAN) : start]
    checked = max((before.rfind(mark) for mark in CHECKED_MARKS), default=-1)
    unchecked = max((before.rfind(mark) for mark in UNCHECKED_MARKS), default=-1)
    if checked >= 0 or unchecked >= 0:
        return checked > unchecked
    after = text[end : end + 12]
    checked_at = min(
        (after.find(mark) for mark in CHECKED_MARKS if mark in after), default=-1
    )
    unchecked_at = min(
        (after.find(mark) for mark in UNCHECKED_MARKS if mark in after), default=-1
    )
    return checked_at >= 0 and (unchecked_at < 0 or checked_at < unchecked_at)


def read_filer_status(window: str) -> FilerStatusReading | None:
    """Read a filer-status checkbox block from a prose window.

    Returns None unless the window carries the block itself (two
    or more status categories named); a lone mention is not a grid.
    """
    text = normalize_text(window)
    found: list[tuple[int, int, str]] = []
    for category in FILER_CATEGORIES:
        for match in _CATEGORY_RE[category].finditer(text):
            found.append((match.start(), match.end(), category))
    claimed: list[tuple[int, int, str]] = []
    for start, end, category in sorted(
        found, key=lambda hit: (hit[0], hit[0] - hit[1])
    ):
        if any(
            start < taken_end and taken_start < end
            for taken_start, taken_end, _ in claimed
        ):
            continue
        claimed.append((start, end, category))
    present = tuple(
        category
        for category in FILER_CATEGORIES
        if any(hit[2] == category for hit in claimed)
    )
    marked = tuple(hit[2] for hit in claimed if _is_marked(text, hit[0], hit[1]))
    if len(present) < 2:
        return None
    return FilerStatusReading(present, marked)


def is_checkbox_fragment(geometry: GeometryText) -> bool:
    """A fragment whose own grid cannot decide filer status."""
    if len(geometry.stubs) > 8:
        return False
    text = geometry.stub_text + " " + normalize_text(geometry.caption)
    if any(mark in text for mark in CHECKED_MARKS + UNCHECKED_MARKS):
        return True
    named = sum(1 for category in FILER_CATEGORIES if category in text)
    return named >= 1 and len(geometry.stubs) <= 8


def classify_filer_status(
    context: TableContext, geometry: GeometryText, caption: str = ""
) -> FilerStatusReading | None:
    """The R-C4 re-encode: decide filer status at window grain.

    The geometry's fragment shape is recorded, never consulted as
    evidence; the window's checkbox block is the discriminating grid.
    """
    reading = read_filer_status(window_from_context(context, caption))
    if reading is None:
        return None
    if not is_checkbox_fragment(geometry) and len(geometry.stubs) > 8:
        return None
    return reading
