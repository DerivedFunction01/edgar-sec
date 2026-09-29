"""Yes/No pair normalization patterns and masked-offset translation.

Private helpers shared by extractor.py and rewrite.py.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from edgar_sec.domain.forms.checkmarks import CANONICAL_CHECKED, CANONICAL_UNCHECKED
from edgar_sec.engine.tables.protection import TableSpan
from edgar_sec.foundation.regex.builder import build_alternation

# ---------------------------------------------------------------------------
# Yes/No word and line patterns
# ---------------------------------------------------------------------------

YES_NO_WORD_RE = re.compile(
    r"\b(?P<answer>yes|no)(?=\s|[:.] |[_\[\(\{/|\\]|$)", re.IGNORECASE
)
YES_NO_LINE_RE = re.compile(
    r"\b(?:yes|no)(?=\s|[:.] |[_\[\(\{/|\\]|$).*"
    r"\b(?:yes|no)(?=\s|[:.] |[_\[\(\{/|\\]|$)",
    re.IGNORECASE,
)

_CHECKED_PATTERNS: tuple[str, ...] = (
    r"_{1,8}\s*[Xx]\s*_{1,8}",
    r"_{1,8}\s*[Xx]",
    r"[Xx]\s*_{1,8}",
    r"_{1,8}\s*[Cc][Kk]\s*_{1,8}",
    r"/\s*[Xx]\s*/",
    r"\|\s*[Xx]\s*\|",
    r"\\\s*[Xx]\s*\\",
    r"\[[Xx]\]",
    r"\bX{1,2}\b",
    r"\bCK\b",
)
_UNCHECKED_PATTERNS: tuple[str, ...] = (
    r"_{1,8}(?:\s+_{1,8})+",
    r"\[ \]",
    r"_{2,}",
    r"\[\s*[_-]{1,8}\s*\]",
    r"\{\s*\}",
    r"/\s{1,8}/",
    r"\|\s{1,8}\|",
    r"\\\s{1,8}\\",
    r"\(\s{1,8}\)",
)
_CHECKED_RE = re.compile(
    build_alternation(_CHECKED_PATTERNS, sort_longest_first=False),
    re.IGNORECASE,
)
_PAIR_MARK_PATTERN = build_alternation(
    (*_CHECKED_PATTERNS, *_UNCHECKED_PATTERNS),
    sort_longest_first=False,
)
_PAIR_RE = re.compile(
    rf"(?:(?P<before>{_PAIR_MARK_PATTERN})\s*)?"
    rf"\b(?P<answer>yes|no)\s*[:.]?\s*"
    rf"(?:(?P<after>{_PAIR_MARK_PATTERN}))?",
    re.IGNORECASE,
)

RE_SEPARATOR_LINE = re.compile(r"^[-=_\s]{3,}$")


def normalize_yes_no_pair_line(line: str) -> str:
    """Canonicalize a line only when both opposite answers are explicitly marked."""
    lower = line.casefold()
    if "yes" not in lower or "no" not in lower:
        return line
    matches = tuple(_PAIR_RE.finditer(line))
    pair_matches: list[re.Match[str]] = []
    for index in range(len(matches) - 1):
        first, second = matches[index : index + 2]
        first_answer = first.group("answer").casefold()
        second_answer = second.group("answer").casefold()
        if {first_answer, second_answer} != {"yes", "no"}:
            continue
        if any(
            match.group("before") and match.group("after") for match in (first, second)
        ):
            continue
        if not all(
            match.group("before") or match.group("after") for match in (first, second)
        ):
            continue
        pair_matches.extend((first, second))
    if not pair_matches:
        return line
    replacements: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()
    for match in pair_matches:
        mark_group = "before" if match.group("before") else "after"
        mark = match.group(mark_group)
        mark_span = (match.start(mark_group), match.end(mark_group))
        if mark_span in seen:
            continue
        seen.add(mark_span)
        replacement = (
            CANONICAL_CHECKED if _CHECKED_RE.fullmatch(mark) else CANONICAL_UNCHECKED
        )
        start = match.start(mark_group)
        end = match.end(mark_group)
        if mark_group == "after" and start == match.end("answer"):
            replacement = f" {replacement}"
        elif mark_group == "before":
            end = match.start("answer")
            replacement = f"{replacement} "
        replacements.append((start, end, replacement))
    for start, end, replacement in reversed(replacements):
        line = line[:start] + replacement + line[end:]
    return line


# ---------------------------------------------------------------------------
# Masked-frame to original-frame offset translation
# ---------------------------------------------------------------------------

_SENTINEL_TEMPLATE = "__SEC_TBL_{position}__"


def build_masked_offset_translator(
    masked: str, spans: tuple[TableSpan, ...]
) -> Callable[[int], int]:
    """Return a callable mapping masked-text offsets to original-text offsets."""
    sentinels: list[tuple[int, int, int, int]] = []
    search_from = 0
    for position, span in enumerate(spans):
        sentinel = _SENTINEL_TEMPLATE.format(position=position)
        sentinel_start = masked.find(sentinel, search_from)
        if sentinel_start == -1:
            continue
        search_from = sentinel_start + len(sentinel)
        sentinels.append((sentinel_start, search_from, span.start, span.end))
    sentinels.sort()

    def translate(masked_offset: int) -> int:
        delta = 0
        for start, end, original_start, original_end in sentinels:
            if masked_offset >= end:
                delta += (original_end - original_start) - (end - start)
            elif masked_offset > start:
                return original_start
            else:
                break
        return masked_offset + delta

    return translate


__all__ = [
    "RE_SEPARATOR_LINE",
    "YES_NO_LINE_RE",
    "YES_NO_WORD_RE",
    "build_masked_offset_translator",
    "normalize_yes_no_pair_line",
]
