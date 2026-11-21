"""Form 12b-25 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form12B25Report(CompanyReport):
    """Specialized projection for Form 12b-25 late-filing notifications."""


__all__ = ["Form12B25Report"]
