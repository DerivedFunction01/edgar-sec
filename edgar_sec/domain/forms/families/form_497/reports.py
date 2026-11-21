"""Form 497 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form497Report(CompanyReport):
    """Specialized projection for Form 497 filings."""


__all__ = ["Form497Report"]
