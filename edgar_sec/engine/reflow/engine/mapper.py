"""Map pre-reflow line numbers to post-reflow line numbers.
Only `ACTION_UNWRAP` changes the line count, so the mapping is downward shifts from each unwrap's
`end_line` onward. A line inside an unwrapped range reports its own source index.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable

from ..types import ACTION_UNWRAP, SpanDecision


def build_line_mapper(
    decisions: tuple[SpanDecision, ...],
) -> Callable[[int], int]:
    """Map pre-reflow line numbers to post-reflow line numbers.
    For ``ACTION_UNWRAP`` every line at or after ``end_line`` shifts down by the lines the unwrap removed.
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
