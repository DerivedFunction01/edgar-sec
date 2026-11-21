"""Tests for chunk division and worker assignment models."""

from __future__ import annotations

import pytest

from edgar_sec.infra.distribution.partition import (
    build_assignment,
    derive_assignment_id,
    divide_chunks,
)


def test_divide_chunks_round_robin() -> None:
    """Verifies deterministic round-robin assignment."""
    division = divide_chunks(5, 2)
    assert division["worker-00"] == (0, 2, 4)
    assert division["worker-01"] == (1, 3)


def test_divide_chunks_single_worker() -> None:
    """Verifies single worker receives all chunks."""
    division = divide_chunks(3, 1)
    assert division["worker-00"] == (0, 1, 2)


def test_divide_chunks_more_workers_than_chunks() -> None:
    """Verifies trailing workers receive empty chunk lists."""
    division = divide_chunks(2, 4)
    assert division["worker-00"] == (0,)
    assert division["worker-01"] == (1,)
    assert division["worker-02"] == ()
    assert division["worker-03"] == ()


def test_divide_chunks_validates_counts() -> None:
    """Verifies negative or zero counts are rejected."""
    with pytest.raises(ValueError, match="worker_count must be >= 1"):
        divide_chunks(5, 0)
    with pytest.raises(ValueError, match="chunk_count must be >= 1"):
        divide_chunks(0, 2)


def test_build_assignment_content_identity() -> None:
    """Verifies assignment content identity is deterministic."""
    asgn1 = build_assignment("meta", "work-1", "1" * 64, "w1", [0, 1, 2])
    asgn2 = build_assignment("meta", "work-1", "1" * 64, "w1", [2, 1, 0])
    assert asgn1.assignment_id == asgn2.assignment_id
    assert asgn1.chunk_ids == (0, 1, 2)
    changed = build_assignment("meta", "work-1", "2" * 64, "w1", [0, 1, 2])
    assert changed.assignment_id != asgn1.assignment_id
