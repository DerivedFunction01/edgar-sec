"""Form F-N report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormFnReport(CompanyReport):
    """Specialized projection for Form F-N agent appointments."""


__all__ = ["FormFnReport"]
