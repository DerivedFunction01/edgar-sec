"""Form N-Q report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormNQReport(CompanyReport):
    """Specialized projection for Form N-Q filings."""


__all__ = ["FormNQReport"]
