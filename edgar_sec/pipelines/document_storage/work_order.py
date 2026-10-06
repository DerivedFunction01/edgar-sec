"""The seam between an input plan and chunk execution.

A work order is replayable and streaming: it yields bounded chunks on demand rather than
holding a plan-wide mapping, so neither the operator nor the worker materializes a plan.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from edgar_sec.domain.document.acquisition import AcquiredSubmission
from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.pipelines.document_storage.candidates import CandidateDecision
from edgar_sec.pipelines.document_storage.processor import ProcessedDocument


@dataclass(frozen=True, slots=True)
class ChunkInput:
    """One executable chunk: its identity and the work it owns."""

    chunk_id: str
    locators: tuple[DocumentLocator, ...]
    occurrences: tuple[FilingOccurrence, ...]


@dataclass(frozen=True, slots=True)
class FilingWork:
    """One locator's decision and the occurrences it must produce."""

    locator: DocumentLocator
    occurrences: tuple[FilingOccurrence, ...]
    filing_date: date | None
    candidate: CandidateDecision
    status: str = ""
    error: str | None = None
    acquired: AcquiredSubmission | None = None
    processed: ProcessedDocument | None = None


@dataclass(frozen=True, slots=True)
class DelegationTarget:
    """A stub decision a worker observed, for the delegation pass to resolve.

    Keyed on the stub primary's locator key so the exhibit second pass can find the
    matching snapshot row.
    """

    document_locator_key: str
    document_path: str
    target_exhibit: str


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


__all__ = [
    "ChunkInput",
    "DelegationTarget",
    "FilingWork",
    "WorkOrder",
]
