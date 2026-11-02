"""Form 11-K report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form11KReport(CompanyReport):
    """Specialized projection for employee plan annual reports."""


__all__ = ["Form11KReport"]
