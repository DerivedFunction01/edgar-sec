"""DRS report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class DrsReport(CompanyReport):
    """Specialized projection for confidential draft registration submissions."""


__all__ = ["DrsReport"]
