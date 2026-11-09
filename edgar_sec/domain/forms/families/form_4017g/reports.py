"""Form 40-17G report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form4017GReport(CompanyReport):
    """Specialized projection for Form 40-17G filings."""


__all__ = ["Form4017GReport"]
