"""Form F-4 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormF4Report(CompanyReport):
    """Specialized projection for Form F-4 registration statements."""


__all__ = ["FormF4Report"]
