"""Allocation-free text counters for large documents.

``str.split()`` and ``str.splitlines()`` materialize a list entry per
word/line; on multi-megabyte filings that is hundreds of thousands of
transient objects per document per call site. These counters scan lazily
and produce the same values as the materializing equivalents for
whitespace-normalized text.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"\S+")


def count_words(text: str) -> int:
    """Count whitespace-separated words without materializing a word list.

    Equivalent to ``len(text.split())``: ``str.split()`` with no arguments
    and ``re``'s Unicode ``\\S+`` runs agree on what separates words, and
    both ignore leading/trailing whitespace.
    """
    if not text:
        return 0
    return sum(1 for _ in _WORD_RE.finditer(text))


def count_lines(text: str) -> int:
    """Count newline-delimited lines without materializing a line list.

    Equivalent to ``len(text.splitlines())`` for text whose only line
    separator is ``\\n`` without a trailing newline (the shape produced by
    the whitespace normalization passes). Other Unicode line separators are
    not counted; callers use this for diagnostics only.
    """
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


__all__ = ["count_lines", "count_words"]
