"""Registration statement family projections over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class RegistrationReport(CompanyReport):
    """Specialized projection for registration statements."""


__all__ = ["RegistrationReport"]
