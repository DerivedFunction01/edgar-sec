"""Monotonic sequence tracking and contiguity validation state machine."""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class MonotonicSequenceTracker(Generic[T]):
    """Tracks strictly non-decreasing ordinal progression in a sequence."""

    def __init__(self, canonical_order: tuple[T, ...]) -> None:
        self._order_map: dict[T, int] = {
            item: idx for idx, item in enumerate(canonical_order)
        }
        self._current_idx: int = -1
        self._visited: set[T] = set()

    @property
    def current_index(self) -> int:
        return self._current_idx

    def get_ordinal(self, identifier: T) -> int | None:
        return self._order_map.get(identifier)

    def validate_group_contiguity(self, identifiers: tuple[T, ...]) -> bool:
        """Verify that multi-item identifiers form an adjacent sequence with delta=1."""
        if len(identifiers) <= 1:
            return True
        for i in range(len(identifiers) - 1):
            curr_ord = self._order_map.get(identifiers[i])
            next_ord = self._order_map.get(identifiers[i + 1])
            if curr_ord is None or next_ord is None or next_ord - curr_ord != 1:
                return False
        return True

    def accept(self, identifier: T) -> bool:
        """Advance state if strictly monotonic; reject anachronisms and repeats."""
        idx = self._order_map.get(identifier)
        if idx is None or idx <= self._current_idx or identifier in self._visited:
            return False
        self._current_idx = idx
        self._visited.add(identifier)
        return True

    def accept_group(self, identifiers: tuple[T, ...]) -> bool:
        """Advance state across contiguous group elements to the last item."""
        if not identifiers or any(item in self._visited for item in identifiers):
            return False
        first_idx = self._order_map.get(identifiers[0])
        if first_idx is None or first_idx <= self._current_idx:
            return False
        if not self.validate_group_contiguity(identifiers):
            return False
        last_idx = self._order_map.get(identifiers[-1])
        if last_idx is None or last_idx < first_idx:
            return False
        self._current_idx = last_idx
        for item in identifiers:
            self._visited.add(item)
        return True

    def is_visited(self, identifier: T) -> bool:
        return identifier in self._visited

    def missing_items(self, canonical_order: tuple[T, ...]) -> tuple[T, ...]:
        """Return canonical items up to current index that were skipped."""
        if self._current_idx < 0:
            return ()
        return tuple(
            item
            for idx, item in enumerate(canonical_order)
            if idx <= self._current_idx and item not in self._visited
        )
