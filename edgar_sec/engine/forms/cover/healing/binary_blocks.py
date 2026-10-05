"""Binary Yes/No block merging for cover checkbox grids: a binary question arrives
as stacked lines — question tail, mark, opposite tail, box+dot spacer — and
collapses to one canonicalized line. A bare bullet is never evidence of one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from edgar_sec.domain.forms.common.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    CONTEXT_CHECKED_SYMBOLS,
    CONTEXT_UNCHECKED_SYMBOLS,
    RE_RAW_CHECKED,
    RE_RAW_UNCHECKED,
    CheckmarkScope,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.patterns import RE_SEPARATOR_LINE

_RE_DASH_ONLY_LINE = RE_SEPARATOR_LINE
_RE_BRACKET_CHECKED = re.compile(r"(\[[Xx]\])(?=[A-Za-z0-9])")
_RE_BRACKET_CHECKED_AFTER = re.compile(r"([A-Za-z0-9])(\[[Xx]\])")
_RE_BRACKET_UNCHECKED = re.compile(r"(\[ \])(?=[A-Za-z0-9])")
_RE_BRACKET_UNCHECKED_AFTER = re.compile(r"([A-Za-z0-9])(\[ \])")
_RE_PAREN_CHECKED = re.compile(r"(\([Xx]\))(?=[A-Za-z0-9])")
_RE_PAREN_CHECKED_AFTER = re.compile(r"([A-Za-z0-9])(\([Xx]\))")

_BARE_CHECKED = ("x", "X")
_RE_BARE_CHECKED = re.compile(
    rf"(?<!\S)(?:{build_alternation(_BARE_CHECKED, auto_escape=True)})(?!\S)",
    re.IGNORECASE,
)

_QUESTION_TAIL_RE = re.compile(r"\b(yes|no)\b[^a-z]*$", re.IGNORECASE)
_RE_CONTEXT_CHECKED = re.compile(
    rf"(?<!\w)(?:{build_alternation(CONTEXT_CHECKED_SYMBOLS, auto_escape=True)})(?!\w)"
)
_RE_CONTEXT_UNCHECKED = re.compile(
    rf"(?<!\w)(?:{build_alternation(CONTEXT_UNCHECKED_SYMBOLS, auto_escape=True)})(?!\w)"
)


def normalize_checkbox_tokens(
    text: str,
    *,
    scope: CheckmarkScope = CheckmarkScope.GLOBAL_SAFE,
) -> str:
    """Normalize safe checkbox tokens, optionally using cover context."""
    text = RE_RAW_CHECKED.sub(CANONICAL_CHECKED, text)
    text = RE_RAW_UNCHECKED.sub(CANONICAL_UNCHECKED, text)
    text = _RE_BARE_CHECKED.sub(CANONICAL_CHECKED, text)
    if scope in (CheckmarkScope.COVER_CONTEXT, CheckmarkScope.ALL):
        text = _RE_CONTEXT_CHECKED.sub(CANONICAL_CHECKED, text)
        text = _RE_CONTEXT_UNCHECKED.sub(CANONICAL_UNCHECKED, text)
    # A canonical token must be space-separated from adjacent words where the
    # source had none ("[X]Annual" -> "[X] Annual", "company[X]" -> "company [X]").
    text = _RE_BRACKET_CHECKED.sub(f"{CANONICAL_CHECKED} ", text)
    text = _RE_BRACKET_CHECKED_AFTER.sub(rf"\1 {CANONICAL_CHECKED}", text)
    text = _RE_BRACKET_UNCHECKED.sub(f"{CANONICAL_UNCHECKED} ", text)
    text = _RE_BRACKET_UNCHECKED_AFTER.sub(rf"\1 {CANONICAL_UNCHECKED}", text)
    text = _RE_PAREN_CHECKED.sub(f"{CANONICAL_CHECKED} ", text)
    text = _RE_PAREN_CHECKED_AFTER.sub(rf"\1 {CANONICAL_CHECKED}", text)
    return text


def _looks_like_mark_head(head: str) -> bool:
    """Return True if a single leading char is plausibly a checkbox mark."""
    if head in "xXoO[]()":
        return True
    if not head.isalpha():
        return True
    return head.isprintable() and not head.isupper()


def classify_mark_line(
    line: str,
    *,
    context: str = "gap",
    scope: CheckmarkScope = CheckmarkScope.GLOBAL_SAFE,
) -> str:
    """Classify a line as a checkbox mark; `context` is its position relative to the
    Yes/No words — "gap", "leading" before a capitalized phrase, or "trailing".
    """
    stripped = line.strip()
    if not stripped:
        return "unknown"
    if RE_RAW_CHECKED.fullmatch(stripped):
        return "checked"
    if RE_RAW_UNCHECKED.fullmatch(stripped):
        return "unchecked"
    if _RE_BARE_CHECKED.fullmatch(stripped):
        return "checked"
    if scope in (CheckmarkScope.COVER_CONTEXT, CheckmarkScope.ALL):
        if _RE_CONTEXT_CHECKED.fullmatch(stripped):
            return "checked"
        if _RE_CONTEXT_UNCHECKED.fullmatch(stripped):
            return "unchecked"
    if context == "leading":
        head = stripped[:1]
        tail = stripped[1:].lstrip()
        if (
            (
                head in "xX"
                or scope in (CheckmarkScope.COVER_CONTEXT, CheckmarkScope.ALL)
            )
            and head.isprintable()
            and tail[:1].isupper()
            and _looks_like_mark_head(head)
        ):
            return "checked"
    return "unknown"


def _is_question_tail(line: str) -> bool:
    """Return True if line ends with a Yes/No question word."""
    return bool(_QUESTION_TAIL_RE.search(line))


def _tail_word(line: str) -> str:
    """Return 'yes' or 'no' for a question-tail line."""
    match = _QUESTION_TAIL_RE.search(line)
    return match.group(1).lower() if match else ""


def _extend_binary_block(
    lines: list[str],
    start: int,
    *,
    scope: CheckmarkScope = CheckmarkScope.GLOBAL_SAFE,
) -> int | None:
    """The end index (exclusive) if a binary block starts at `start`: head (question
    word) + gap marks + tail (opposite word) + trailing mark.
    """
    head_word = _tail_word(lines[start])
    target = "no" if head_word == "yes" else "yes"
    i = start + 1
    n = len(lines)
    saw_context_mark = False
    while i < n and i <= start + 10:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped == ".":
            saw_context_mark = True
            i += 1
            continue
        if _is_question_tail(line) and _tail_word(line) == target:
            end = i + 1
            next_i = i + 1
            while next_i < n and not lines[next_i].strip():
                next_i += 1
            if (
                next_i < n
                and lines[next_i].strip() == "."
                or next_i < n
                and classify_mark_line(lines[next_i], context="gap", scope=scope)
                in (
                    "checked",
                    "unchecked",
                )
            ):
                end = next_i + 1
            return end if saw_context_mark or end > i + 1 else None
        if classify_mark_line(line, context="gap", scope=scope) in (
            "checked",
            "unchecked",
        ):
            saw_context_mark = True
            i += 1
            continue
        return None
    return None


def _find_binary_blocks(
    lines: list[str], *, scope: CheckmarkScope = CheckmarkScope.GLOBAL_SAFE
) -> list[tuple[int, int]]:
    """Find (start, end) index pairs for each Yes/No binary block."""
    blocks: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        if not _is_question_tail(lines[i]):
            i += 1
            continue
        end = _extend_binary_block(lines, i, scope=scope)
        if end is None:
            i += 1
            continue
        blocks.append((i, end))
        i = end
    return blocks


def _render_binary_block(
    lines: list[str], *, scope: CheckmarkScope = CheckmarkScope.GLOBAL_SAFE
) -> str:
    """Join a binary block's lines into a single canonicalized line."""
    parts = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == ".":
            continue
        if _RE_DASH_ONLY_LINE.fullmatch(stripped):
            continue
        if (
            len(stripped) == 1
            and classify_mark_line(stripped, context="gap", scope=scope) == "unchecked"
        ):
            stripped = CANONICAL_UNCHECKED
        elif (
            len(stripped) == 1
            and classify_mark_line(stripped, context="gap", scope=scope) == "checked"
        ):
            stripped = CANONICAL_CHECKED
        parts.append(stripped)
    return normalize_checkbox_tokens(" ".join(parts), scope=scope)


def merge_yes_no_binary_blocks(
    lines: Sequence[str],
    *,
    scope: CheckmarkScope = CheckmarkScope.GLOBAL_SAFE,
) -> list[str]:
    """Collapse Yes/No binary question blocks onto single lines, in either order and
    across recognized, bare x/o, and single-character Wingdings marks.
    """
    blocks = _find_binary_blocks(list(lines), scope=scope)
    if not blocks:
        # A cover boundary alone is not evidence for a free-standing bullet.
        return [normalize_checkbox_tokens(line) for line in lines]
    merged: list[str] = []
    cursor = 0
    for start, end in blocks:
        merged.extend(lines[cursor:start])
        merged.append(_render_binary_block(lines[start:end], scope=scope))
        cursor = end
    merged.extend(lines[cursor:])
    return merged


__all__ = [
    "classify_mark_line",
    "merge_yes_no_binary_blocks",
    "normalize_checkbox_tokens",
]
