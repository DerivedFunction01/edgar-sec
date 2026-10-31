"""Current report family projections over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class CurrentReport(CompanyReport):
    """Specialized projection for current reports."""


__all__ = ["CurrentReport"]
