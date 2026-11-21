"""Prospectus report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form424BReport(CompanyReport):
    """Specialized projection for Rule 424 prospectus filings."""


__all__ = ["Form424BReport"]
