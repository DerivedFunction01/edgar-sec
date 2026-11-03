"""Free writing prospectus report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormFWPReport(CompanyReport):
    """Specialized projection for free writing prospectus filings."""


__all__ = ["FormFWPReport"]
