"""Deterministic target planning filter options for filing catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PlanFilterOptions:
    """Filter criteria applied during deterministic target planning."""

    forms: tuple[str, ...] = ()
    document_suffixes: tuple[str, ...] | None = None
    dates: str | None = None
    limit: int | None = None
    accession_limit: int | None = None
    min_exhibit_like: int | None = None
    cohort: str | None = None
    xbrl_only: bool = False
    accessions: tuple[str, ...] | None = None

    def to_request_dict(self) -> dict[str, Any]:
        """Convert filter options to canonical request properties for plan hashing."""
        return {
            "forms": list(self.forms),
            "document_suffixes": (
                list(self.document_suffixes)
                if self.document_suffixes is not None
                else None
            ),
            "dates": self.dates,
            "limit": self.limit,
            "accession_limit": self.accession_limit,
            "min_exhibit_like": self.min_exhibit_like,
            "cohort": self.cohort,
            "xbrl_only": self.xbrl_only,
            "accessions": (
                list(sorted(self.accessions)) if self.accessions is not None else None
            ),
        }


__all__ = ["PlanFilterOptions"]
