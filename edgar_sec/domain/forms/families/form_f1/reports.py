"""Form F-1 / F-2 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormF1Report(CompanyReport):
    """Specialized projection for Form F-1 and F-2 registration statements."""


__all__ = ["FormF1Report"]
