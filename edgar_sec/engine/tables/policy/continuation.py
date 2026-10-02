"""Recognizing when a block after a table row is that row's continuation.

A statement row whose description wraps onto the following lines carries no
numeric cells of its own, so the reflow engine sees two prose-shaped blocks where
a filing has one row. The signal is positional: a continuation line places its
numbers under the columns the previous rows already established.
"""

from __future__ import annotations

from edgar_sec.foundation.text.patterns import RE_SENTENCE_TERMINAL, RE_SEPARATOR_LINE

from ...reflow.types import ReflowPolicy
from ..numeric_cells import is_numeric_cell
from ..tokens import numeric_cell_starts as _numeric_cell_starts

_TOTAL_KEYWORDS = ("total", "net", "less", "subtotal")


def is_table_row_continuation(
    previous: tuple[str, ...],
    continuation: tuple[str, ...],
    policy: ReflowPolicy | None = None,
) -> bool:
    """Return whether numeric columns indicate a wrapped table row."""
    if not continuation or any(
        policy is not None
        and policy.is_page_boundary_line is not None
        and policy.is_page_boundary_line(line.strip())
        for line in continuation
    ):
        return False
    nonblank = tuple(line.strip() for line in continuation if line.strip())
    raw_nonblank = tuple(line for line in continuation if line.strip())
    if not nonblank:
        return False
    if all(RE_SEPARATOR_LINE.fullmatch(line) for line in nonblank):
        return True
    prior_positions = tuple(
        position for line in previous for position in _numeric_cell_starts(line)
    )
    next_positions = tuple(
        position for line in continuation for position in _numeric_cell_starts(line)
    )
    if not prior_positions or not next_positions:
        return False
    aligned_cells = sum(
        any(abs(position - prior_position) <= 3 for prior_position in prior_positions)
        for position in next_positions
    )
    if aligned_cells >= 2:
        if any(
            len(line.split()) >= 5
            and (
                RE_SENTENCE_TERMINAL.search(line)
                or any(mark in line for mark in (". ", "? ", "! "))
            )
            for line in nonblank
        ):
            return False
        for line in raw_nonblank[1:]:
            if RE_SEPARATOR_LINE.fullmatch(line.strip()):
                continue
            content_start = len(line) - len(line.lstrip())
            line_positions = _numeric_cell_starts(line)
            if not (
                any(
                    abs(position - prior_position) <= 3
                    for position in line_positions
                    for prior_position in prior_positions
                )
                or any(
                    abs(content_start - prior_position) <= 3
                    for prior_position in prior_positions
                )
            ):
                return False
        return True
    if aligned_cells < 1 or len(nonblank) > 3:
        return False
    for line in nonblank:
        words = line.split()
        if len(words) > 5 and RE_SENTENCE_TERMINAL.search(line):
            return False
        if RE_SEPARATOR_LINE.match(line):
            continue
        has_total = False
        all_numeric = True
        for w in words:
            if not has_total and w.lower() in _TOTAL_KEYWORDS:
                has_total = True
            if all_numeric and not is_numeric_cell(w):
                all_numeric = False
        if not (all_numeric or has_total):
            return False
    return True


__all__ = ["is_table_row_continuation"]
