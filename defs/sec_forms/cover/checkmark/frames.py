"""Masked-frame to original-frame coordinate translation for table sentinels."""

from __future__ import annotations

from collections.abc import Callable

from defs.tables.protection import TableSpan

_SENTINEL_TEMPLATE = "__SEC_TBL_{position}__"


def build_masked_offset_translator(
    masked: str, spans: tuple[TableSpan, ...]
) -> Callable[[int], int]:
    """Return a callable mapping masked-text offsets to original-text offsets.

    Masked table sentinels shorten the document, so offsets measured on the
    masked frame drift after each table. The translator restores the original
    coordinates using each sentinel's masked range and the corresponding
    original table span. Offsets inside a sentinel map to the span start.
    """

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


__all__ = ["build_masked_offset_translator"]
