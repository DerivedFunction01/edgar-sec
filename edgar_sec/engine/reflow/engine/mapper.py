"""Map pre-reflow line numbers to post-reflow line numbers.

A reflow is not line-count preserving: unwrapping a block of ``n`` hard-wrapped
lines collapses it to one, so every later line in the document moves up. A
decision trace recorded against the source is therefore only usable if it can be
read in the coordinate frame of the output, and that is what the mapper is for.

Only ``ACTION_UNWRAP`` changes the line count. Every other action emits its lines
unchanged, so the mapping is a sequence of downward shifts applied from each
unwrap decision's ``end_line`` onward, and it can be answered in ``O(log k)`` for
``k`` unwrap decisions.

A line *inside* an unwrapped range reports its own source index rather than the
index of the single line it was absorbed into. Every decision boundary the
reflow produces is either the first line of an unwrap block — which the output
keeps at that index — or at or after a prior ``end_line``, so the mapper is
exact for the trace it exists to translate. Interior lines of a collapsed block
have no distinct output line to name.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable

from ..types import ACTION_UNWRAP, SpanDecision


def build_line_mapper(
    decisions: tuple[SpanDecision, ...],
) -> Callable[[int], int]:
    """Map pre-reflow line numbers to post-reflow line numbers.

    ``SpanDecision`` records half-open ``[start_line, end_line)`` ranges.
    For ``ACTION_UNWRAP`` decisions, every line at or after ``end_line``
    shifts down by ``end_line - start_line - 1``, the number of lines the
    unwrap removed.  Other actions preserve line counts.

    The returned function runs in ``O(log k)`` where ``k`` is the number
    of unwrap decisions.
    """
    breakpoints: list[int] = []
    cumulative: list[int] = []
    running = 0
    for d in decisions:
        if d.action == ACTION_UNWRAP:
            removed = d.end_line - d.start_line - 1
            if removed > 0:
                running += removed
                breakpoints.append(d.end_line)
                cumulative.append(running)

    if not breakpoints:
        return lambda line: line

    def map_line(line: int) -> int:
        idx = bisect.bisect_right(breakpoints, line) - 1
        if idx < 0:
            return line
        return line - cumulative[idx]

    return map_line


__all__ = ["build_line_mapper"]
