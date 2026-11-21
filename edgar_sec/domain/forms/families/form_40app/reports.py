"""Form 40-APP report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form40AppReport(CompanyReport):
    """Specialized projection for Form 40-APP filings."""


__all__ = ["Form40AppReport"]
