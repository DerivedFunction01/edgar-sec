"""Schedule 14A report projection over filing aggregates."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.reports import CompanyReport


@dataclass(frozen=True, slots=True)
class Form14AReport(CompanyReport):
    """Specialized projection for proxy and information statements."""


__all__ = ["Form14AReport"]
