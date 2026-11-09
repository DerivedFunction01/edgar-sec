"""Form S-6 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormS6Report(CompanyReport):
    """Specialized projection for Form S-6 filings."""


__all__ = ["FormS6Report"]
