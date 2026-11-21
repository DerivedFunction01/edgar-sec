"""Form 24F-2 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form24F2Report(CompanyReport):
    """Specialized projection for Form 24F-2 filings."""


__all__ = ["Form24F2Report"]
