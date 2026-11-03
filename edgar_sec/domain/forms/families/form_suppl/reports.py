"""SUPPL report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class FormSupplReport(CompanyReport):
    """Specialized projection for MJDS prospectus supplements."""


__all__ = ["FormSupplReport"]
