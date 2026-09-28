"""Unit tests for foundation.runtime.partitions."""

from __future__ import annotations

from edgar_sec.foundation.runtime.partitions import (
    divide_ids_among_workers,
    parse_id_selection,
)


def test_parse_id_selection_handles_ranges_and_lists() -> None:
    assert parse_id_selection("1-3,5,8-10") == (1, 2, 3, 5, 8, 9, 10)
    assert parse_id_selection("  4  ") == (4,)
    assert parse_id_selection("") == ()


def test_parse_id_selection_rejects_non_numeric_input() -> None:
    try:
        parse_id_selection("abc")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_divide_ids_among_workers_preserves_all_elements() -> None:
    divided = divide_ids_among_workers((1, 2, 3, 4, 5, 6, 7), worker_count=3)
    assert len(divided) == 3
    assert sorted(item for bucket in divided for item in bucket) == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
    ]


def test_divide_ids_handles_more_workers_than_ids() -> None:
    divided = divide_ids_among_workers((1, 2), worker_count=5)
    assert sorted(item for bucket in divided for item in bucket) == [1, 2]
