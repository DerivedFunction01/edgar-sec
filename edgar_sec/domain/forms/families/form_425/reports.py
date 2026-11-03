"""Rule 425 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form425Report(CompanyReport):
    """Specialized projection for Rule 425 communication filings."""


__all__ = ["Form425Report"]
