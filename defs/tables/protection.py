"""Exact protection of existing tagged tables inside plain-text documents.

Legacy ASCII/SGML filings contain ``<TABLE>...</TABLE>`` blocks (with
``<S>``/``<C>`` cell markers) that must survive any whitespace-oriented
normalization byte-for-byte. This module masks those spans behind
collision-safe sentinels so later passes cannot see their internal layout,
then restores them exactly.

An unclosed ``<TABLE>`` is protected through end-of-text: reflowing an open
tag's content is worse than leaving it untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["ProtectedText", "TableSpan", "mask_tagged_tables", "restore_tagged_tables"]

_SENTINEL_PREFIX = "__SEC_TBL_"
_SENTINEL_SUFFIX = "__"


@dataclass(frozen=True, slots=True)
class TableSpan:
    """One protected tagged-table span in the original text."""

    start: int
    end: int
    text: str

    @property
    def complete(self) -> bool:
        return "</table" in self.text.lower()

    @property
    def line_ranges(self) -> tuple[tuple[int, int], ...]:
        """Return half-open line ranges [(start, end), ...] for this span."""
        start_line = self.text.count("\n", 0, self.start)
        end_line = self.text.count("\n", 0, self.end)
        return ((start_line, end_line),)


class ProtectedText:
    """Immutable protected-text boundary for tagged tables.

    Callers use this single abstraction instead of pairing
    :func:`mask_tagged_tables` and :func:`restore_tagged_tables` directly.
    """

    def __init__(self, text: str) -> None:
        self._original = text
        self._masked, self._spans = mask_tagged_tables(text)
        self._restored = False

    @property
    def masked(self) -> str:
        """Text with tagged tables replaced by sentinels."""
        return self._masked

    @property
    def spans(self) -> tuple[TableSpan, ...]:
        """All protected table spans in source order."""
        return self._spans

    @property
    def complete_spans(self) -> tuple[TableSpan, ...]:
        """Only complete (closed) table spans."""
        return tuple(s for s in self._spans if s.complete)

    @property
    def unterminated_spans(self) -> tuple[TableSpan, ...]:
        """Only unterminated table spans."""
        return tuple(s for s in self._spans if not s.complete)

    @property
    def span_count(self) -> int:
        """Number of protected table spans."""
        return len(self._spans)

    @property
    def original(self) -> str:
        """Return the original text with all tables restored exactly once."""
        if not self._restored:
            self._restored = True
            return restore_tagged_tables(self._masked, self._spans)
        return self._original

    def transform_outside(self, func: Callable[[str], str]) -> str:
        """Apply ``func`` only to text outside protected table spans.

        Table spans are replaced by whitespace-preserving placeholders
        of the same length so that character offsets remain valid.
        """
        result = self._masked
        result = func(result)
        return restore_tagged_tables(result, self._spans)

    def transform_span(self, span_index: int, func: Callable[[str], str]) -> str:
        """Apply ``func`` to a single protected table span by index."""
        if span_index < 0 or span_index >= len(self._spans):
            raise IndexError(
                f"span index {span_index} out of range for {len(self._spans)} spans"
            )
        span = self._spans[span_index]
        placeholder = " " * (span.end - span.start)
        masked = self._masked[: span.start] + placeholder + self._masked[span.end :]
        result = func(masked)
        return restore_tagged_tables(result, self._spans)

    def line_preserving_mask(self) -> tuple[str, tuple[TableSpan, ...]]:
        """Return masked text and spans, preserving line structure.

        Unlike the sentinel-based mask, this keeps table-internal newlines
        intact so line-coordinate calculations remain valid.
        """
        return self._masked, self._spans

    def __len__(self) -> int:
        return len(self._original)

    def __bool__(self) -> bool:
        return len(self._spans) > 0


def mask_tagged_tables(text: str) -> tuple[str, tuple[TableSpan, ...]]:
    """Mask every complete or unterminated tagged table with a sentinel.

    Returns the masked text plus the exact spans in source order. When the
    source already contains the sentinel prefix, masking is skipped entirely
    and the input is returned unchanged with no spans — callers must treat
    that as "no reflow possible" rather than guessing.
    """
    if not text or _SENTINEL_PREFIX in text:
        return text, ()

    spans: list[TableSpan] = []
    pieces: list[str] = []
    cursor = 0
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
        spans.append(TableSpan(start=index, end=end, text=text[index:end]))
        pieces.append(text[cursor:index])
        pieces.append(f"{_SENTINEL_PREFIX}{len(spans) - 1}{_SENTINEL_SUFFIX}")
        cursor = end
        if not complete:
            break
        index = lowered.find("<table", end)

    if not spans:
        return text, ()
    pieces.append(text[cursor:])
    return "".join(pieces), tuple(spans)


def restore_tagged_tables(text: str, spans: tuple[TableSpan, ...]) -> str:
    """Restore exact original table spans replaced by :func:`mask_tagged_tables`."""
    for position, span in enumerate(spans):
        sentinel = f"{_SENTINEL_PREFIX}{position}{_SENTINEL_SUFFIX}"
        if sentinel not in text:
            raise ValueError(f"masked table sentinel {position} missing at restore")
        text = text.replace(sentinel, span.text)
    return text
