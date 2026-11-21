"""Form 15 report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form15Report(CompanyReport):
    """Specialized projection for Form 15 deregistration notices."""


__all__ = ["Form15Report"]
