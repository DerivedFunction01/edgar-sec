"""Ownership report family projections over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import FormReport


@dataclass(frozen=True, slots=True)
class OwnershipReport(FormReport):
    """Specialized projection for insider ownership reports."""

    def xml(self) -> bytes | None:
        path = self.filing.primary_storage_path
        if path is not None and path.is_file():
            return path.read_bytes()
        return None


__all__ = ["OwnershipReport"]
