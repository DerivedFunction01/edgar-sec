"""Domain dataclasses for SEC Form C filings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FormCKind(StrEnum):
    """Form C kinds, dispatched by the header submission type."""

    OFFERING = "offering"
    PROGRESS = "progress"
    ANNUAL_REPORT = "annual_report"
    TERMINATION = "termination"
    WITHDRAWAL = "withdrawal"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CIssuer:
    """Issuer block shared by every Form C kind."""

    name: str | None
    commission_cik: str | None
    commission_file_number: str | None
    legal_status_form: str | None
    jurisdiction: str | None
    website: str | None
    co_issuer_count: int


@dataclass(frozen=True, slots=True)
class FormCDocument:
    """Structured representation of a Form C submission at review depth."""

    submission_type: str | None
    kind: FormCKind
    live_test_flag: str | None
    filer_ciks: tuple[str, ...]
    issuer: CIssuer
    has_offering_information: bool
    has_progress_update: bool
    has_annual_financials: bool
    offering_amount: str | None
    maximum_offering_amount: str | None


__all__ = ["CIssuer", "FormCDocument", "FormCKind"]
