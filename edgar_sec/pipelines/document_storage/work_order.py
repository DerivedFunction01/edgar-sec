"""The seam between an input plan and chunk execution.

A work order is replayable and streaming: it yields bounded chunks on demand rather than
holding a plan-wide mapping, so neither the operator nor the worker materializes a plan.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence


@dataclass(frozen=True, slots=True)
class ChunkInput:
    """One executable chunk: its identity and the work it owns."""

    chunk_id: str
    locators: tuple[DocumentLocator, ...]
    occurrences: tuple[FilingOccurrence, ...]


class WorkOrder(Protocol):
    """A replayable source of chunks derived from an input plan.

    Replayable rather than single-pass: the delegation pass re-reads only the locators
    it needs, which is what keeps a whole plan out of memory.
    """

    @property
    def chunk_count(self) -> int:
        """Total chunks a full read yields."""

    def iter_chunks(self) -> Iterator[ChunkInput]:
        """Yield chunks in the work order's stable sequence."""

    def locators_by_key(self, keys: Iterable[str]) -> dict[str, DocumentLocator]:
        """Return the named locators, reading no more of the plan than they need."""


__all__ = ["ChunkInput", "WorkOrder"]
