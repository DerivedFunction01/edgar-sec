"""Form 40-17F2 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form4017F2Report(CompanyReport):
    """Specialized projection for Form 40-17F2 filings."""


__all__ = ["Form4017F2Report"]
