"""Tender report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class TenderReport(CompanyReport):
    """Specialized projection for tender offer statements."""


__all__ = ["TenderReport"]
