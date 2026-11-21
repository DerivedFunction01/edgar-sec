"""Form 40-F report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form40FReport(CompanyReport):
    """Specialized projection for Form 40-F annual wrappers."""


__all__ = ["Form40FReport"]
