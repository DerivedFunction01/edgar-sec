"""Parser-facing mark canonicalization shared by the form families.

A mark is recognized by the shared domain vocabulary; this module only decides how a
recognized mark is written back into parser input.
"""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    CHECKMARK_MARK_RE,
    RE_FILLED_CHECKED,
    mark_token_state,
)


def canonicalize_mark_tokens(text: str) -> str:
    """Replace every recognized mark in text with its canonical token.

    A mark with no state, such as an unfilled underscore run, is left as it is.
    """

    def _replace(match: re.Match[str]) -> str:
        state = mark_token_state(match.group(0).strip(), allow_bare=True)
        if state is None:
            return match.group(0)
        return CANONICAL_CHECKED if state == "checked" else CANONICAL_UNCHECKED

    return CHECKMARK_MARK_RE.sub(_replace, text)


def mark_state_in(text: str) -> str | None:
    """Return the state of the first recognized mark in text."""
    for match in CHECKMARK_MARK_RE.finditer(text):
        state = mark_token_state(match.group(0).strip(), allow_bare=True)
        if state is not None:
            return state
    return None


def canonicalize_filled_marks(text: str) -> str:
    """Rewrite an underscore-delimited checked fill to the canonical token.

    The rewrite separates the mark from an adjacent label, because a label glued to
    a fill is not word-boundary delimited. An underscore-only run is left as it is.
    """

    def _replace(match: re.Match[str]) -> str:
        start, end = match.span()
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        lead = "" if not before or before.isspace() else " "
        trail = "" if not after or after.isspace() else " "
        return f"{lead}{CANONICAL_CHECKED}{trail}"

    return RE_FILLED_CHECKED.sub(_replace, text)


def canonicalize_filled_marks_in_span(
    text: str, *, start_line: int = 0, end_line: int | None = None
) -> tuple[str, bool]:
    """Canonicalize checked fills inside a line-bounded span."""
    lines = text.splitlines(keepends=True)
    stop = len(lines) if end_line is None else min(len(lines), end_line)
    changed = False
    for index in range(max(0, start_line), stop):
        normalized = canonicalize_filled_marks(lines[index])
        if normalized != lines[index]:
            lines[index] = normalized
            changed = True
    return "".join(lines), changed


__all__ = [
    "canonicalize_filled_marks",
    "canonicalize_filled_marks_in_span",
    "canonicalize_mark_tokens",
    "mark_state_in",
]
