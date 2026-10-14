"""Polymorphic form projections over filing aggregates."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from edgar_sec.domain.document.aggregate import FilingAggregate


@dataclass(frozen=True, slots=True)
class FormReport(ABC):
    """Abstract base class for polymorphic form-family report projections."""

    filing: FilingAggregate

    @property
    def form(self) -> str:
        return self.filing.form

    @property
    def accession(self) -> str:
        return str(self.filing.accession)


@dataclass(frozen=True, slots=True)
class CompanyReport(FormReport):
    """Specialized base projection for periodic and current reports."""

    def text(self) -> str | None:
        path = self.filing.primary_storage_path
        if path is not None and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
        return None


@dataclass(frozen=True, slots=True)
class GenericReport(FormReport):
    """Fallback projection for unspecialized SEC forms."""


def get_report_projection(filing: FilingAggregate) -> FormReport:
    """Project a filing aggregate into its specialized form-family report."""
    from edgar_sec.domain.forms.families.processing_profiles import get_family_profile

    profile = get_family_profile(filing.form)
    if profile is not None and profile.report_class is not None:
        return profile.report_class(filing)
    return GenericReport(filing)


__all__ = [
    "CompanyReport",
    "FormReport",
    "GenericReport",
    "get_report_projection",
]
