"""Tests for monotonic sequence tracking and contiguity validation."""

from __future__ import annotations

from edgar_sec.engine.forms.sections.sequence import MonotonicSequenceTracker


def test_monotonic_sequence_accepts_forward_steps() -> None:
    order = ("1", "1A", "1B", "2", "3", "7", "8")
    tracker = MonotonicSequenceTracker[str](order)
    assert tracker.accept("1") is True
    assert tracker.accept("1A") is True
    assert tracker.accept("2") is True
    assert tracker.accept("7") is True


def test_monotonic_sequence_rejects_backward_anachronisms() -> None:
    order = ("1", "1A", "2", "3", "7", "8")
    tracker = MonotonicSequenceTracker[str](order)
    assert tracker.accept("7") is True
    assert tracker.accept("7") is False
    assert tracker.accept("1") is False
    assert tracker.accept("2") is False
    assert tracker.current_index == order.index("7")


def test_contiguity_validator_accepts_contiguous_lists() -> None:
    order = ("1", "1A", "1B", "1C", "2", "3")
    tracker = MonotonicSequenceTracker[str](order)
    assert tracker.validate_group_contiguity(("1", "1A", "1B")) is True
    assert tracker.validate_group_contiguity(("1A", "1B", "1C")) is True


def test_contiguity_validator_rejects_disjoint_lists() -> None:
    order = ("1", "1A", "1B", "1C", "2", "3")
    tracker = MonotonicSequenceTracker[str](order)
    assert tracker.validate_group_contiguity(("1A", "1C")) is False
    assert tracker.validate_group_contiguity(("1", "2")) is False


def test_integer_sequence_contiguity_for_financial_notes() -> None:
    tracker = MonotonicSequenceTracker[int](tuple(range(1, 20)))
    assert tracker.validate_group_contiguity((4, 5)) is True
    assert tracker.validate_group_contiguity((1, 2, 3)) is True
    assert tracker.validate_group_contiguity((2, 7)) is False


def test_accept_group_advances_to_last_item() -> None:
    order = ("1", "1A", "1B", "2", "3")
    tracker = MonotonicSequenceTracker[str](order)
    assert tracker.accept_group(("1", "1A", "1B")) is True
    assert tracker.current_index == order.index("1B")
    assert tracker.accept("2") is True
    assert tracker.accept("1A") is False
