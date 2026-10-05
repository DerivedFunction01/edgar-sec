"""Translating pre-reflow line numbers into post-reflow line numbers.
Lines at or after an unwrap decision’s `end_line` shift up by the lines unwrap
removed; a line inside a collapsed block reports its own source index.
"""

from __future__ import annotations

from edgar_sec.engine.reflow.engine.mapper import build_line_mapper
from edgar_sec.engine.reflow.types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    SpanDecision,
)


def test_no_decisions_maps_every_line_to_itself() -> None:
    mapper = build_line_mapper(())
    assert [mapper(line) for line in range(5)] == [0, 1, 2, 3, 4]


def test_a_single_line_decision_is_the_identity() -> None:
    mapper = build_line_mapper(
        (
            SpanDecision(ACTION_UNWRAP, 5, 6, 0.7),
            SpanDecision(ACTION_PRESERVE, 6, 9, 1.0),
        )
    )
    assert [mapper(line) for line in range(4, 10)] == [4, 5, 6, 7, 8, 9]


def test_an_unwrap_shifts_only_the_lines_after_it() -> None:
    mapper = build_line_mapper((SpanDecision(ACTION_UNWRAP, 10, 14, 0.7),))
    assert [mapper(line) for line in range(9, 16)] == [9, 10, 11, 12, 13, 11, 12]


def test_a_collapse_shifts_every_later_line_up() -> None:
    mapper = build_line_mapper(
        (
            SpanDecision(ACTION_PRESERVE, 0, 10, 1.0),
            SpanDecision(ACTION_UNWRAP, 10, 14, 0.7),
            SpanDecision(ACTION_PRESERVE, 14, 20, 1.0),
        )
    )
    assert [mapper(line) for line in range(0, 21, 2)] == [
        0,
        2,
        4,
        6,
        8,
        10,
        12,
        11,
        13,
        15,
        17,
    ]


def test_several_collapses_accumulate() -> None:
    mapper = build_line_mapper(
        (
            SpanDecision(ACTION_UNWRAP, 0, 3, 0.7),
            SpanDecision(ACTION_PRESERVE, 3, 5, 1.0),
            SpanDecision(ACTION_UNWRAP, 5, 9, 0.7),
            SpanDecision(ACTION_PRESERVE, 9, 12, 1.0),
        )
    )
    assert [mapper(line) for line in range(13)] == [
        0,
        1,
        2,
        1,
        2,
        3,
        4,
        5,
        6,
        4,
        5,
        6,
        7,
    ]


def test_a_tag_decision_never_moves_a_line() -> None:
    mapper = build_line_mapper(
        (
            SpanDecision(ACTION_TAG_AND_PRESERVE, 0, 10, 0.8),
            SpanDecision(ACTION_PRESERVE, 10, 20, 1.0),
        )
    )
    assert [mapper(line) for line in range(0, 21, 5)] == [0, 5, 10, 15, 20]


def test_every_decision_boundary_maps_to_its_output_line() -> None:
    decisions = (
        SpanDecision(ACTION_UNWRAP, 0, 4, 0.7),
        SpanDecision(ACTION_PRESERVE, 4, 6, 1.0),
        SpanDecision(ACTION_TAG_AND_PRESERVE, 6, 12, 0.8),
        SpanDecision(ACTION_UNWRAP, 12, 15, 0.7),
    )
    mapper = build_line_mapper(decisions)
    # 15 source lines minus 3 minus 2 collapsed; each decision's range starts where
    # the output shows it.
    assert mapper(0) == 0
    assert mapper(4) == 1
    assert mapper(6) == 3
    assert mapper(12) == 9
