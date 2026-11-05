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


_ORDER7 = ("0", "1", "2", "3", "4", "5", "6")


def _assemble(events: list[tuple[str, ...]]):
    tracker = MonotonicSequenceTracker[str](_ORDER7)
    return tracker.assemble_sequence(events)


def test_assembly_keeps_both_sides_of_an_adjacent_swap() -> None:
    assembly = _assemble([("0",), ("1",), ("2",), ("3",), ("5",), ("4",), ("6",)])
    assert assembly.disordered is False
    assert assembly.displaced == (5,)
    assert set(assembly.spine) | set(assembly.displaced) == set(range(7))


def test_assembly_readmits_an_item_displaced_across_the_spine() -> None:
    assembly = _assemble([("6",), ("0",), ("1",), ("2",), ("3",), ("4",), ("5",)])
    assert assembly.disordered is False
    assert assembly.displaced == (0,)
    assert assembly.spine == (1, 2, 3, 4, 5, 6)


def test_assembly_readmits_two_independent_local_faults() -> None:
    assembly = _assemble([("1",), ("0",), ("3",), ("2",)])
    assert assembly.disordered is False
    assert set(assembly.spine) | set(assembly.displaced) == set(range(4))


def test_assembly_marks_a_globally_disordered_stream() -> None:
    assembly = _assemble([("3",), ("2",), ("1",), ("0",)])
    assert assembly.disordered is True
    assert assembly.displaced == ()


def test_assembly_marks_mutually_inverted_displacements_disordered() -> None:
    assembly = _assemble([("4",), ("1",), ("2",), ("3",), ("0",)])
    assert assembly.disordered is True
    assert assembly.displaced == ()


def test_assembly_duplicate_is_rejected_never_displaced() -> None:
    assembly = _assemble([("1",), ("2",), ("2",), ("3",)])
    assert assembly.disordered is False
    assert assembly.rejected == (2,)
    assert assembly.displaced == ()


def test_assembly_grouped_event_loses_a_claimed_ordinal_whole() -> None:
    assembly = _assemble([("5",), ("4", "5"), ("6",)])
    assert assembly.rejected == (1,)
    assert assembly.displaced == ()


def test_assembly_empty_and_singleton_streams() -> None:
    empty = _assemble([])
    assert empty.spine == () and empty.displaced == () and empty.disordered is False
    single = _assemble([("4",)])
    assert (
        single.spine == (0,) and single.displaced == () and single.disordered is False
    )
