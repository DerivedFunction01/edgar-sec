"""Domain-neutral text, phrase, and line-healing infrastructure."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from defs.regex import build_alternation, compact_alternation
from defs.text.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    RAW_CHECKED_TOKENS,
    RAW_UNCHECKED_TOKENS,
    RE_RAW_CHECKED,
    RE_RAW_UNCHECKED,
)
from defs.text.dates import MONTH_RE

_BARE_CHECKED = ("x", "X", "\u00fe", "\u00fd")
_BARE_UNCHECKED = ("o", "O")
_RE_BARE_CHECKED = re.compile(
    rf"(?<!\S)(?:{build_alternation(_BARE_CHECKED, auto_escape=True)})(?!\S)",
    re.IGNORECASE,
)
_RE_BARE_UNCHECKED = re.compile(
    rf"(?<!\S)(?:{build_alternation(_BARE_UNCHECKED, auto_escape=True)})(?!\S)",
    re.IGNORECASE,
)

_ALL_CHECKBOX_PATTERNS = build_alternation(
    (*RAW_CHECKED_TOKENS, *RAW_UNCHECKED_TOKENS), auto_escape=True
)

_NEGATIVE_BOUNDARY_TERMS = [
    r"\(\d+\)",
    r"\([a-z]\)",
    _ALL_CHECKBOX_PATTERNS,
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

YES_NO_TAIL_RE = re.compile(r"\b(yes|no)\.?\s*$", re.IGNORECASE)
_STANDALONE_MARK_RE = re.compile(
    r"^(?:"
    rf"(?:{RE_RAW_CHECKED.pattern})"
    rf"|(?:{RE_RAW_UNCHECKED.pattern})"
    r"|x|o|\u00fe|\u00fd)\s*[.;]?\s*$",
    re.IGNORECASE,
)
_MAX_BINARY_CHAIN_GAP = 3
_QUESTION_TAIL_RE = re.compile(r"\b(yes|no)\b[^a-z]*$", re.IGNORECASE)
_INLINE_YES_NO_RE = re.compile(r"\byes\b.*\bno\b|\bno\b.*\byes\b", re.IGNORECASE)
_WINGDINGS_UNCHECKED = frozenset({"r"})


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
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]

    collapsed: list[str] = []
    for line in lines:
        if line:
            collapsed.append(line)
        elif collapsed and collapsed[-1] != "":
            collapsed.append("")
    return "\n".join(collapsed).strip()


def normalize_checkbox_tokens(text: str) -> str:
    """Normalize diverse checked and unchecked characters to canonical [X] and [ ]."""
    text = RE_RAW_CHECKED.sub(CANONICAL_CHECKED, text)
    text = RE_RAW_UNCHECKED.sub(CANONICAL_UNCHECKED, text)
    text = _RE_BARE_CHECKED.sub(CANONICAL_CHECKED, text)
    text = _RE_BARE_UNCHECKED.sub(CANONICAL_UNCHECKED, text)
    # Ensure a single space separates a canonical checkbox token from adjacent
    # words when the source cell had no spacing (e.g. "[X]Annual report...").
    text = re.sub(r"(\[[ Xx]\])(?=[A-Za-z0-9])", r"\1 ", text)
    text = re.sub(r"([A-Za-z0-9])(\[[ Xx]\])", r"\1 \2", text)
    return text


def strip_boxdot_spacers(lines: list[str]) -> list[str]:
    """Remove lone '.' lines that are box+dot spacers between Yes/No."""
    return [ln for ln in lines if ln.strip() != "."]


def classify_mark_line(line: str, *, context: str = "gap") -> str:
    """Classify a line as a checkbox mark.

    Args:
        line: The line to classify.
        context: Position of the mark relative to Yes/No words:
            - "gap": mark alone on its own line between Yes/No tails.
            - "leading": mark at start of line before a capitalized phrase
              (e.g. "x ANNUAL REPORT..." from the Mark One grid).
            - "trailing": mark at end of line after a Yes/No word.

    Returns: "checked", "unchecked", or "unknown".
    """
    stripped = line.strip()
    if not stripped:
        return "unknown"
    if RE_RAW_CHECKED.fullmatch(stripped):
        return "checked"
    if RE_RAW_UNCHECKED.fullmatch(stripped):
        return "unchecked"
    if _RE_BARE_CHECKED.match(stripped):
        return "checked"
    if _RE_BARE_UNCHECKED.match(stripped):
        return "unchecked"
    if len(stripped) == 1 and stripped.isprintable():
        if stripped.lower() in _WINGDINGS_UNCHECKED:
            return "unchecked"
        return "checked" if context in ("gap", "leading", "trailing") else "unknown"
    if context == "leading":
        head = stripped[:1]
        tail = stripped[1:].lstrip()
        if head.isprintable() and tail[:1].isupper() and _looks_like_mark_head(head):
            return "checked"
    return "unknown"


def _looks_like_mark_head(head: str) -> bool:
    """Return True if a single leading char is plausibly a checkbox mark."""
    if head in "xXoO[]()":
        return True
    if not head.isalpha():
        return True
    return head.isprintable() and not head.isupper()


def _is_question_tail(line: str) -> bool:
    """Return True if line ends with a Yes/No question word."""
    return bool(_QUESTION_TAIL_RE.search(line))


def strip_alphanumeric_words(text: str) -> list[str]:
    """Extract lowercase word tokens, keeping intra-word hyphens and apostrophes."""
    return re.findall(r"[a-zA-Z0-9'\-]+", text.lower())


def _token_to_regex(token: str | Sequence[str]) -> re.Pattern:
    """Convert string or sequence of alternation choices to a compiled word pattern."""
    if isinstance(token, str):
        pat = token if "|" in token or token.startswith(r"\d") else re.escape(token)
    else:
        pat = compact_alternation(token)
    return re.compile(rf"(?i)^{pat}$")


def _anchor_to_regex(anchor: str | Sequence[str] | None) -> re.Pattern | None:
    """Convert string or sequence of anchor keywords to a compiled search pattern."""
    if anchor is None:
        return None
    if isinstance(anchor, str):
        pat = anchor if "|" in anchor else re.escape(anchor)
    else:
        pat = compact_alternation(anchor)
    return re.compile(rf"(?i)\b(?:{pat})\b")


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
        and re.match(r"^[a-z0-9\(\:\,\.\)]", line_b, re.IGNORECASE)
    ) or bool(
        re.search(r"\b(?:ended|from)\s*$", line_a, re.IGNORECASE)
        and MONTH_RE.match(line_b)
    )


def heal_split_lines(
    lines: Sequence[str],
    rules: Sequence[PhraseSequenceRule],
) -> list[str]:
    """Slide across lines and heal broken phrase fragments across newlines."""
    healed: list[str] = []
    i = 0
    num_lines = len(lines)

    while i < num_lines:
        line = lines[i].strip()
        if not line:
            healed.append("")
            i += 1
            continue

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

        healed.append(line)
        i += 1

    return healed


def merge_yes_no_binary_blocks(lines: Sequence[str]) -> list[str]:
    """Collapse Yes/No binary question blocks onto single lines.

    Handles every variant found in the fixture:
      - recognized marks (brackets, symbols, entities)
      - bare x/o
      - Wingdings single-char marks (R, T, S, ...)
      - box+dot spacers (stripped)
      - prefix/suffix positioning
      - inverse order (No before Yes)
    """
    blocks = _find_binary_blocks(list(lines))
    if not blocks:
        return [normalize_checkbox_tokens(line) for line in lines]
    merged: list[str] = []
    cursor = 0
    for start, end in blocks:
        merged.extend(lines[cursor:start])
        merged.append(_render_binary_block(lines[start:end]))
        cursor = end
    merged.extend(lines[cursor:])
    return merged


def _find_binary_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Find (start, end) index pairs for each Yes/No binary block."""
    blocks: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        if not _is_question_tail(lines[i]):
            i += 1
            continue
        end = _extend_binary_block(lines, i)
        if end is None:
            i += 1
            continue
        blocks.append((i, end))
        i = end
    return blocks


def _extend_binary_block(lines: list[str], start: int) -> int | None:
    """Return the end index (exclusive) if a binary block starts at `start`.

    Structure: head(question word) + gap_marks + tail(opposite word) + trailing_mark.
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
                and classify_mark_line(lines[next_i], context="gap")
                in (
                    "checked",
                    "unchecked",
                )
            ):
                end = next_i + 1
            return end if saw_context_mark or end > i + 1 else None
        if classify_mark_line(line, context="gap") in ("checked", "unchecked"):
            saw_context_mark = True
            i += 1
            continue
        return None
    return None


def _tail_word(line: str) -> str:
    """Return 'yes' or 'no' for a question-tail line."""
    match = _QUESTION_TAIL_RE.search(line)
    return match.group(1).lower() if match else ""


def _render_binary_block(lines: list[str]) -> str:
    """Join a binary block's lines into a single canonicalized line."""
    parts = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == ".":
            continue
        if (
            len(stripped) == 1
            and classify_mark_line(stripped, context="gap") == "unchecked"
        ):
            stripped = CANONICAL_UNCHECKED
        elif (
            len(stripped) == 1
            and classify_mark_line(stripped, context="gap") == "checked"
        ):
            stripped = CANONICAL_CHECKED
        parts.append(stripped)
    return normalize_checkbox_tokens(" ".join(parts))


__all__ = [
    "CANONICAL_CHECKED",
    "CANONICAL_UNCHECKED",
    "NEGATIVE_BOUNDARY_RE",
    "RE_RAW_CHECKED",
    "RE_RAW_UNCHECKED",
    "PhraseSequenceRule",
    "classify_mark_line",
    "heal_split_lines",
    "merge_yes_no_binary_blocks",
    "normalize_checkbox_tokens",
    "normalize_whitespace_and_tabs",
    "should_join_two_lines",
    "strip_alphanumeric_words",
    "strip_boxdot_spacers",
]
