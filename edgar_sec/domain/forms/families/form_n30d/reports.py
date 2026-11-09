"""Form N-30D report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormN30DReport(CompanyReport):
    """Specialized projection for Form N-30D filings."""


__all__ = ["FormN30DReport"]
