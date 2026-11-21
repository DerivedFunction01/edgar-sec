"""Annual report family projections over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class AnnualReport(CompanyReport):
    """Specialized projection for annual reports."""


__all__ = ["AnnualReport"]
