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

from dataclasses import dataclass

__all__ = ["TableSpan", "mask_tagged_tables", "restore_tagged_tables"]

_SENTINEL = "\x00"


@dataclass(frozen=True, slots=True)
class TableSpan:
    """One protected tagged-table span in the original text."""

    start: int
    end: int
    text: str

    @property
    def complete(self) -> bool:
        return "</table" in self.text.lower()


def mask_tagged_tables(text: str) -> tuple[str, tuple[TableSpan, ...]]:
    """Mask every complete or unterminated tagged table with a sentinel.

    Returns the masked text plus the exact spans in source order. When the
    source already contains the sentinel byte, masking is skipped entirely
    and the input is returned unchanged with no spans — callers must treat
    that as "no reflow possible" rather than guessing.
    """
    if not text or _SENTINEL in text:
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
        pieces.append(f"{_SENTINEL}{len(spans) - 1}{_SENTINEL}")
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
        sentinel = f"{_SENTINEL}{position}{_SENTINEL}"
        if sentinel not in text:
            raise ValueError(f"masked table sentinel {position} missing at restore")
        text = text.replace(sentinel, span.text)
    return text
