"""Form SD report projection."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormSDReport(CompanyReport):
    """Specialized projection for Form SD."""


__all__ = ["FormSDReport"]
