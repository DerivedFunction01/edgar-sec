"""Section 12 registration cluster report projection."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form12RegReport(CompanyReport):
    """Specialized projection for the 25 / 8-A / 8-B cluster."""


__all__ = ["Form12RegReport"]
