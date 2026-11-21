"""Form 18-K report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form18KReport(CompanyReport):
    """Specialized projection for Form 18-K filings."""


__all__ = ["Form18KReport"]
