"""Form F-3 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormF3Report(CompanyReport):
    """Specialized projection for Form F-3 registration statements."""


__all__ = ["FormF3Report"]
