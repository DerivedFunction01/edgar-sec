"""Domain-neutral text, phrase, and line-healing infrastructure."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from edgar_sec.foundation.regex.builder import build_alternation, compact_alternation
from edgar_sec.foundation.text.dates import MONTH_RE

_RE_MULTI_SPACE = re.compile(r"[ \t]+")
_RE_WORD_TOKENS = re.compile(r"[a-zA-Z0-9'\-]+")
_RE_LOWER_START = re.compile(r"^[a-z0-9\(\:\,\.\)]")
_RE_ENDED_FROM = re.compile(r"\b(?:ended|from)\s*$", re.IGNORECASE)

_NEGATIVE_BOUNDARY_TERMS = [
    r"\(\d+\)",
    r"\([a-z]\)",
    r"\[[ xX_]\]",
    r"\([ xX_]\)",
    r"Item\s+\d+",
    r"Part\s+[IVX]+",
    r"<TABLE",
    r"<S>",
    r"<C>",
    r"Co-Registrants:",
    r"Securities\s+registered",
]
NEGATIVE_BOUNDARY_RE = re.compile(
    rf"^(?:{build_alternation(_NEGATIVE_BOUNDARY_TERMS)})",
    re.IGNORECASE,
)

_TRAILING_PREPOSITIONS = [
    "of",
    "the",
    "for",
    "and",
    "or",
    "in",
    "to",
    "from",
    "pursuant to",
    ",",
]
RE_TRAILING_CONTINUATION = re.compile(
    rf"\b(?:{compact_alternation(_TRAILING_PREPOSITIONS)})\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PhraseSequenceRule:
    """A multi-word phrase sequence where split line breaks should be healed."""

    name: str
    tokens: list[str | Sequence[str]]
    anchor: str | Sequence[str] | None = None


def normalize_whitespace_and_tabs(text: str) -> str:
    """Normalize line endings, non-breaking spaces, and intra-line whitespace runs."""
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_RE_MULTI_SPACE.sub(" ", line).strip() for line in text.splitlines()]

    collapsed: list[str] = []
    for line in lines:
        if line:
            collapsed.append(line)
        elif collapsed and collapsed[-1] != "":
            collapsed.append("")
    return "\n".join(collapsed).strip()


def strip_alphanumeric_words(text: str) -> list[str]:
    """Extract lowercase word tokens, keeping intra-word hyphens and apostrophes."""
    return _RE_WORD_TOKENS.findall(text.lower())


_TOKEN_REGEX_CACHE: dict[object, re.Pattern] = {}
_ANCHOR_REGEX_CACHE: dict[object, re.Pattern | None] = {}


def _frozen_pattern_key(value: object) -> object:
    """Return a hashable cache key for a token/anchor value."""
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return tuple(_frozen_pattern_key(item) for item in value)
    return value


def _build_token_regex(token: str | Sequence[str]) -> re.Pattern:
    if isinstance(token, str):
        pat = token if "|" in token or r"\d" in token else re.escape(token)
    else:
        pat = compact_alternation(token)
    return re.compile(rf"(?i)^(?:{pat})$")


def _build_anchor_regex(anchor: str | Sequence[str] | None) -> re.Pattern | None:
    if anchor is None:
        return None
    if isinstance(anchor, str):
        pat = anchor if "|" in anchor else re.escape(anchor)
    else:
        pat = compact_alternation(anchor)
    return re.compile(rf"(?i)\b(?:{pat})\b")


def _token_to_regex(token: str | Sequence[str]) -> re.Pattern:
    """Convert string or sequence of alternation choices to a compiled word pattern."""
    key = _frozen_pattern_key(token)
    pattern = _TOKEN_REGEX_CACHE.get(key)
    if pattern is None:
        pattern = _build_token_regex(token)
        _TOKEN_REGEX_CACHE[key] = pattern
    return pattern


def _anchor_to_regex(anchor: str | Sequence[str] | None) -> re.Pattern | None:
    """Convert string or sequence of anchor keywords to a compiled search pattern."""
    key = _frozen_pattern_key(anchor)
    pattern = _ANCHOR_REGEX_CACHE.get(key)
    if key not in _ANCHOR_REGEX_CACHE:
        pattern = _build_anchor_regex(anchor)
        _ANCHOR_REGEX_CACHE[key] = pattern
    return pattern


def should_join_two_lines(
    line_a: str,
    line_b: str,
    rules: Sequence[PhraseSequenceRule],
) -> bool:
    """Check if line_a and line_b should be joined into a single line."""
    if not line_a or not line_b:
        return False

    if NEGATIVE_BOUNDARY_RE.search(line_b):
        return False

    if line_b.startswith("(") and line_b.endswith(")") and not line_a.startswith("("):
        return False

    words_a = strip_alphanumeric_words(line_a)
    words_b = strip_alphanumeric_words(line_b)
    if not words_a or not words_b:
        return False

    last_word = words_a[-1]
    first_word = words_b[0]
    combined_context = f"{line_a} {line_b}"

    for rule in rules:
        anchor_pat = _anchor_to_regex(rule.anchor)
        if anchor_pat and not anchor_pat.search(combined_context):
            continue
        for idx in range(len(rule.tokens) - 1):
            pat_a = _token_to_regex(rule.tokens[idx])
            pat_b = _token_to_regex(rule.tokens[idx + 1])
            if pat_a.search(last_word) and pat_b.search(first_word):
                return True

    return bool(
        RE_TRAILING_CONTINUATION.search(line_a)
        # A title-cased caption is a new field, not a continuation. Explicit
        # phrase rules handle known uppercase banners; this fallback stays
        # conservative and only joins lowercase continuation text.
        and _RE_LOWER_START.match(line_b)
    ) or bool(_RE_ENDED_FROM.search(line_a) and MONTH_RE.match(line_b))


def heal_split_lines(
    lines: Sequence[str],
    rules: Sequence[PhraseSequenceRule],
) -> list[str]:
    """Slide across lines and heal broken phrase fragments across newlines.

    Leading indentation is layout, not damage: every emitted line keeps the
    original leading whitespace of its first source line so cover orientation
    (centering, two-column captions) survives healing unchanged. Joined
    fragments adopt the base indentation of the line that started the phrase.
    """
    healed: list[str] = []
    i = 0
    num_lines = len(lines)

    while i < num_lines:
        original = lines[i]
        line = original.strip()
        if not line:
            healed.append("")
            i += 1
            continue
        base_indent = original[: len(original) - len(original.lstrip())]

        while i + 1 < num_lines:
            next_idx = i + 1
            candidate_line = lines[next_idx].strip()
            if not candidate_line:
                if next_idx + 1 < num_lines and lines[next_idx + 1].strip():
                    candidate_line = lines[next_idx + 1].strip()
                    next_idx = next_idx + 1
                else:
                    break

            if line.startswith("<") or candidate_line.startswith("<"):
                break

            if should_join_two_lines(line, candidate_line, rules):
                line = f"{line} {candidate_line}"
                i = next_idx
            else:
                break

        healed.append(base_indent + line)
        i += 1

    return healed


__all__ = [
    "NEGATIVE_BOUNDARY_RE",
    "PhraseSequenceRule",
    "heal_split_lines",
    "normalize_whitespace_and_tabs",
    "should_join_two_lines",
    "strip_alphanumeric_words",
]
