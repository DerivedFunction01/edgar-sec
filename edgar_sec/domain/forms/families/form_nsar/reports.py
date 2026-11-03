"""Form NSAR report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormNSARReport(CompanyReport):
    """Specialized projection for Form NSAR filings."""


__all__ = ["FormNSARReport"]
