"""Ownership report family projections over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import FormReport


@dataclass(frozen=True, slots=True)
class OwnershipReport(FormReport):
    """Specialized projection for insider ownership reports."""

    def xml(self) -> bytes | None:
        return self.filing.raw()


__all__ = ["OwnershipReport"]
