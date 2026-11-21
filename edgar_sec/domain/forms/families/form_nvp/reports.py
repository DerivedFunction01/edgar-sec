"""Form N-VP report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormNVPReport(CompanyReport):
    """Specialized projection for Form N-VP filings."""


__all__ = ["FormNVPReport"]
