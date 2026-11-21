"""Form N-CSR report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormNCsrReport(CompanyReport):
    """Specialized projection for Form N-CSR filings."""


__all__ = ["FormNCsrReport"]
