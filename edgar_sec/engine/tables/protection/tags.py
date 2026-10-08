"""Byte-exact protection of ``<TABLE>`` spans inside plain-text documents.
Historical ASCII/SGML filings carry ``<TABLE>...</TABLE>`` blocks marked up with ``<S>``/``<C>`` cell delimiters. Those blocks are alignment-sensitive: reflowing one scrambles every column. This module masks each span behind a collision-safe sentinel so later passes cannot see inside it, then restores the exact original bytes. An unclosed ``<TABLE>`` is protected through end-of-text — reflowing the content of an open tag is worse than leaving it alone. Every prose-rewriting stage (HTML cleaning, break injection, cover healing, whitespace normalization, reflow) must mask before it rewrites. This module is the single leaf they share; there is no second masking protocol in the tree.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

_SENTINEL_PREFIX = "__SEC_TBL_"
_SENTINEL_SUFFIX = "__"
_RE_RESTORE_SENTINEL = re.compile(
    rf"{re.escape(_SENTINEL_PREFIX)}(\d+){re.escape(_SENTINEL_SUFFIX)}"
)
TAGGED_TABLE_OPEN_RE = re.compile(r"<TABLE\b", re.IGNORECASE)
TAGGED_TABLE_CLOSE_RE = re.compile(r"</TABLE\s*>", re.IGNORECASE)
_RE_TABLE_OPEN_WITH_SPACE = re.compile(r"[ \t]*<TABLE\b", re.IGNORECASE)
_RE_TABLE_CLOSE_WITH_SPACE = re.compile(r"</TABLE\s*>[ \t]*", re.IGNORECASE)
_RE_TABLE_OPEN_TAG = re.compile(r"<TABLE\b[^>]*>", re.IGNORECASE)
_RE_TABLE_CLOSE_TAG = re.compile(r"</TABLE\s*>", re.IGNORECASE)

# Whitespace normalization passes must treat whitespace adjacent to these tokens as a line
# separator, never as a space.
SENTINEL_PREFIX = _SENTINEL_PREFIX
SENTINEL_SUFFIX = _SENTINEL_SUFFIX


@dataclass(frozen=True, slots=True)
class TableSpan:
    """One protected tagged-table span in the original text.
    ``start_line``/``end_line`` resolve against the whole document at discovery.
    """

    start: int
    end: int
    text: str
    start_line: int = 0
    end_line: int = 0

    @property
    def complete(self) -> bool:
        """True when the span carries its own ``</TABLE>`` closing tag."""
        return "</table" in self.text.lower()

    @property
    def line_ranges(self) -> tuple[tuple[int, int], ...]:
        """Half-open ``(start_line, end_line)`` range covered by this span."""
        return ((self.start_line, self.end_line),)


def _sentinel_token(position: int) -> str:
    """Return the mask token for table span ``position``."""
    return f"{_SENTINEL_PREFIX}{position}{_SENTINEL_SUFFIX}"


def _masked_sentinel_starts(spans: tuple[TableSpan, ...]) -> tuple[int, ...]:
    """Return where each sentinel begins inside :func:`mask_tagged_tables` output.
    Masked offsets drift from source offsets, so slicing masked text by ``span.start`` is wrong.
    """
    starts: list[int] = []
    cursor = 0
    for position, span in enumerate(spans):
        cursor += span.start - cursor
        starts.append(cursor)
        cursor += len(_sentinel_token(position))
    return tuple(starts)


class ProtectedText:
    """Immutable protected-text boundary around tagged tables."""

    def __init__(self, text: str) -> None:
        self._original = text
        self._masked, self._spans = mask_tagged_tables(text)
        self._masked_starts = _masked_sentinel_starts(self._spans)
        self._restored = False

    @property
    def masked(self) -> str:
        """Text with every tagged table replaced by its sentinel."""
        return self._masked

    @property
    def spans(self) -> tuple[TableSpan, ...]:
        """All protected table spans in source order."""
        return self._spans

    @property
    def complete_spans(self) -> tuple[TableSpan, ...]:
        """Only the closed table spans."""
        return tuple(s for s in self._spans if s.complete)

    @property
    def unterminated_spans(self) -> tuple[TableSpan, ...]:
        """Only the spans that run to end-of-text."""
        return tuple(s for s in self._spans if not s.complete)

    @property
    def span_count(self) -> int:
        """Number of protected table spans."""
        return len(self._spans)

    @property
    def original(self) -> str:
        """The original text with every table restored, exactly once."""
        if not self._restored:
            self._restored = True
            return restore_tagged_tables(self._masked, self._spans)
        return self._original

    def transform_outside(self, func: Callable[[str], str]) -> str:
        """Apply ``func`` to the text with tables masked, then restore them."""
        return restore_tagged_tables(func(self._masked), self._spans)

    def transform_span(self, span_index: int, func: Callable[[str], str]) -> str:
        """Apply ``func`` to one protected table span, addressed by index.
        Every *other* span stays masked, so the rewritten span cannot collide with its neighbours.
        """
        if span_index < 0 or span_index >= len(self._spans):
            raise IndexError(
                f"span index {span_index} out of range for {len(self._spans)} spans"
            )
        pieces: list[str] = []
        cursor = 0
        for position, span in enumerate(self._spans):
            masked_start = self._masked_starts[position]
            pieces.append(self._masked[cursor:masked_start])
            if position == span_index:
                pieces.append(func(span.text))
            else:
                pieces.append(_sentinel_token(position))
            cursor = masked_start + len(_sentinel_token(position))
        pieces.append(self._masked[cursor:])
        rewritten = "".join(pieces)
        remaining = tuple(s for i, s in enumerate(self._spans) if i != span_index)
        return restore_tagged_tables(rewritten, remaining)

    def line_preserving_mask(self) -> tuple[str, tuple[TableSpan, ...]]:
        """Masked text plus spans, for callers that need line coordinates."""
        return self._masked, self._spans

    def __len__(self) -> int:
        return len(self._original)

    def __bool__(self) -> bool:
        return len(self._spans) > 0


def find_table_spans(text: str) -> tuple[TableSpan, ...]:
    """Find every complete or unterminated tagged table span, in source order.
    Also returns ``()`` when the text already carries the sentinel prefix: re-masking would nest sentinels and corrupt it.
    """
    if not text or _SENTINEL_PREFIX in text or "<table" not in text.lower():
        return ()

    spans: list[TableSpan] = []
    lowered = text.lower()
    index = lowered.find("<table")
    while index != -1:
        close_index = lowered.find("</table", index)
        if close_index == -1:
            end = len(text)
            complete = False
        else:
            end = lowered.find(">", close_index)
            end = len(text) if end == -1 else end + 1
            complete = True
        spans.append(
            TableSpan(
                start=index,
                end=end,
                text=text[index:end],
                start_line=text.count("\n", 0, index),
                end_line=text.count("\n", 0, end),
            )
        )
        if not complete:
            break
        index = lowered.find("<table", end)

    return tuple(spans)


def mask_tagged_tables(text: str) -> tuple[str, tuple[TableSpan, ...]]:
    """Replace every table span with ``__SEC_TBL_{n}__`` and return the spans.
    An input that already carries a sentinel comes back unchanged: nothing there may be rewritten.
    """
    spans = find_table_spans(text)
    if not spans:
        return text, ()

    pieces: list[str] = []
    cursor = 0
    for position, span in enumerate(spans):
        pieces.append(text[cursor : span.start])
        pieces.append(f"{_SENTINEL_PREFIX}{position}{_SENTINEL_SUFFIX}")
        cursor = span.end

    pieces.append(text[cursor:])
    return "".join(pieces), spans


def restore_tagged_tables(text: str, spans: tuple[TableSpan, ...]) -> str:
    """Reinstate the exact original bytes for every masked table span.
    Verified, not assumed: a sentinel set that does not match the spans raises rather than quietly dropping a table.
    """
    if not spans:
        return text

    span_texts = [span.text for span in spans]
    seen_positions: set[int] = set()

    def _replace_sentinel(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        seen_positions.add(idx)
        return span_texts[idx] if idx < len(span_texts) else match.group(0)

    restored = _RE_RESTORE_SENTINEL.sub(_replace_sentinel, text)
    if len(seen_positions) != len(spans):
        for position in range(len(spans)):
            if position not in seen_positions:
                raise ValueError(f"masked table sentinel {position} missing at restore")

    return restored


def strip_table_wrapper_tags(text: str) -> str:
    """Remove the ``<TABLE>`` wrapper elements while keeping the table body."""
    result = _RE_TABLE_OPEN_TAG.sub("", text)
    return _RE_TABLE_CLOSE_TAG.sub("", result)


def ensure_table_tag_boundaries(text: str) -> str:
    """Put restored table tags on standalone lines without editing contents."""

    def _open(match: re.Match[str]) -> str:
        if match.start() == 0 or text[match.start() - 1] == "\n":
            return match.group(0)
        return f"\n{match.group(0).lstrip()}"

    result = _RE_TABLE_OPEN_WITH_SPACE.sub(_open, text)

    def _close(match: re.Match[str]) -> str:
        tag = match.group(0).rstrip()
        if match.end() < len(result) and result[match.end()] != "\n":
            return f"{tag}\n"
        return tag

    return _RE_TABLE_CLOSE_WITH_SPACE.sub(_close, result)


__all__ = [
    "SENTINEL_PREFIX",
    "SENTINEL_SUFFIX",
    "TAGGED_TABLE_CLOSE_RE",
    "TAGGED_TABLE_OPEN_RE",
    "ProtectedText",
    "TableSpan",
    "ensure_table_tag_boundaries",
    "find_table_spans",
    "mask_tagged_tables",
    "restore_tagged_tables",
    "strip_table_wrapper_tags",
]
