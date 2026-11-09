"""Monotonic sequence tracking and contiguity validation state machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SequenceAssembly(Generic[T]):
    """Spine / displaced / rejected partition of an event stream.

    Indices address the assemble_sequence input; on a disordered
    assembly the caller keeps the spine and rejects the rest.
    """

    spine: tuple[int, ...]
    displaced: tuple[int, ...]
    rejected: tuple[int, ...]
    disordered: bool


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

    def select_longest_run(self, events: list[tuple[T, ...]]) -> tuple[int, ...]:
        """Indices of the longest subsequence of events monotonic in canonical
        order (weighted by identifier count; ties keep earliest positions).
        """
        spans: list[tuple[int, int, int] | None] = []
        for identifiers in events:
            ordinals: list[int] = []
            for item in identifiers:
                ordn = self._order_map.get(item)
                if ordn is None:
                    break
                ordinals.append(ordn)
            if (
                len(ordinals) == len(identifiers)
                and ordinals
                and all(b > a for a, b in zip(ordinals, ordinals[1:]))
            ):
                spans.append((ordinals[0], ordinals[-1], len(identifiers)))
            else:
                spans.append(None)
        best: list[tuple[int, tuple[int, ...]] | None] = [None] * len(events)
        for i, span in enumerate(spans):
            if span is None:
                continue
            lo, _, weight = span
            chosen = (weight, (i,))
            for j in range(i):
                prev = best[j]
                prev_span = spans[j]
                if prev is None or prev_span is None or prev_span[1] >= lo:
                    continue
                extended = (prev[0] + weight, prev[1] + (i,))
                if extended[0] > chosen[0] or (
                    extended[0] == chosen[0] and extended[1] < chosen[1]
                ):
                    chosen = extended
            best[i] = chosen
        result: tuple[int, tuple[int, ...]] | None = None
        for entry in best:
            if entry is None:
                continue
            if (
                result is None
                or entry[0] > result[0]
                or (entry[0] == result[0] and entry[1] < result[1])
            ):
                result = entry
        return result[1] if result is not None else ()

    def _event_span(self, identifiers: tuple[T, ...]) -> tuple[int, int] | None:
        """Ordinal span of one event, or None when it cannot be placed."""
        if not identifiers:
            return None
        ordinals: list[int] = []
        for item in identifiers:
            ordn = self._order_map.get(item)
            if ordn is None:
                return None
            ordinals.append(ordn)
        if any(b <= a for a, b in zip(ordinals, ordinals[1:])):
            return None
        return ordinals[0], ordinals[-1]

    def assemble_sequence(self, events: list[tuple[T, ...]]) -> SequenceAssembly[T]:
        """Partition events into the canonical spine plus displaced items.

        First disjoint claimant wins an ordinal; later claimants are
        duplicates. Displaced events rise canonically, inverting the spine.
        """
        spans = [self._event_span(identifiers) for identifiers in events]
        claimed: set[T] = set()
        admitted: list[int] = []
        rejected: list[int] = []
        for pos, identifiers in enumerate(events):
            if spans[pos] is None or any(item in claimed for item in identifiers):
                rejected.append(pos)
                continue
            admitted.append(pos)
            claimed.update(identifiers)
        spine_sub = self.select_longest_run([events[pos] for pos in admitted])
        spine = tuple(admitted[i] for i in spine_sub)
        spine_set = set(spine)
        displaced = tuple(pos for pos in admitted if pos not in spine_set)
        spine_spans = [
            (other, spans[other]) for other in spine if spans[other] is not None
        ]
        disordered = False
        prev_hi: int | None = None
        for pos in displaced:
            span = spans[pos]
            if span is None:  # admitted events always carry a span
                disordered = True
                break
            if prev_hi is not None and span[0] <= prev_hi:
                disordered = True
                break
            prev_hi = span[1]
            inverts = any(
                (pos < other and span[0] > other_span[1])
                or (pos > other and span[1] < other_span[0])
                for other, other_span in spine_spans
            )
            if not inverts:
                disordered = True
                break
        if disordered:
            displaced = ()
        return SequenceAssembly(
            spine=spine,
            displaced=displaced,
            rejected=tuple(rejected),
            disordered=disordered,
        )

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
