from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ClientSession",
    "CurrentFiling",
    "ReadContext",
    "WorkingSet",
]


@dataclass(frozen=True, slots=True)
class WorkingSet:
    """A named selection: its accession set plus the retained result object."""

    accessions: frozenset[str]
    result: Any = None

    def __len__(self) -> int:
        return len(self.accessions)


@dataclass(slots=True)
class ReadContext:
    """Where reads resolve: the engine mode and the snapshot selector."""

    mode: str = "fast"
    snapshot: str = "main"


@dataclass(frozen=True, slots=True)
class CurrentFiling:
    """The drill-down position: an accession and its retained aggregate."""

    accession: str
    aggregate: Any = None


class ClientSession:
    """Held operator state; the facade is built lazily on first access."""

    def __init__(
        self,
        facade: Any = None,
        *,
        read_context: ReadContext | None = None,
        workers: int | None = None,
    ) -> None:
        self._facade = facade
        self.workers = workers
        self.sets: dict[str, WorkingSet] = {}
        self.current_set_name: str = ""
        self.read_context = read_context or ReadContext()
        self.current_filing: CurrentFiling | None = None
        self.last_run_record: str = ""

    @property
    def facade(self) -> Any:
        """The held facade, constructing the real client only when asked."""
        if self._facade is None:
            from edgar_sec.apps.client.facade import Edgar

            self._facade = Edgar()
        return self._facade

    @property
    def current_set(self) -> WorkingSet | None:
        """The working set the current set name denotes, if any."""
        return self.sets.get(self.current_set_name)

    def add_set(
        self, name: str, accessions: Iterable[str], result: Any = None
    ) -> WorkingSet:
        """Store a named set and make it the current set."""
        working = WorkingSet(accessions=frozenset(accessions), result=result)
        self.sets[name] = working
        self.current_set_name = name
        return working

    def select_filing(self, accession: str, aggregate: Any = None) -> CurrentFiling:
        """Move the drill-down position to one filing."""
        self.current_filing = CurrentFiling(accession=accession, aggregate=aggregate)
        return self.current_filing

    def clear_filing(self) -> None:
        """Clear the drill-down position."""
        self.current_filing = None

    def satisfies(self, requires: str) -> bool:
        """Whether this session currently meets one context requirement."""
        if requires == "none":
            return True
        if requires == "selection":
            return self.current_set is not None
        if requires == "current_filing":
            return self.current_filing is not None and bool(
                self.current_filing.accession
            )
        if requires == "snapshot_context":
            return bool(self.read_context.snapshot)
        return False
