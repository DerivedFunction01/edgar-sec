"""Form F-6 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormF6Report(CompanyReport):
    """Specialized projection for Form F-6 depositary registrations."""


__all__ = ["FormF6Report"]
