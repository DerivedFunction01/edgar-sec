"""N-23C notice family report projections over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormN23C1Report(CompanyReport):
    """Specialized projection for Form N-23C-1 filings."""


@dataclass(frozen=True, slots=True)
class FormN23C2Report(CompanyReport):
    """Specialized projection for Form N-23C-2 filings."""


@dataclass(frozen=True, slots=True)
class FormN23C3Report(CompanyReport):
    """Specialized projection for Form N-23C-3 filings."""


__all__ = [
    "FormN23C1Report",
    "FormN23C2Report",
    "FormN23C3Report",
]
