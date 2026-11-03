"""MJDS family report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormMjdsReport(CompanyReport):
    """Specialized projection for MJDS registration statements."""


__all__ = ["FormMjdsReport"]
