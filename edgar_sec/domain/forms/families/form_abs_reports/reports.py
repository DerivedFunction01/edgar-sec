"""ABS text reports (10-D / ABS-15G) report projection."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormAbsReportsReport(CompanyReport):
    """Specialized projection for the 10-D / ABS-15G text reports."""


__all__ = ["FormAbsReportsReport"]
