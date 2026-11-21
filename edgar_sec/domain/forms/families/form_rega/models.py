"""Domain dataclasses for SEC Regulation A filings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RegAKind(StrEnum):
    """Reg A kinds, dispatched by header submission type or form code."""

    OFFERING = "offering"
    ANNUAL_REPORT = "annual_report"
    EXIT_REPORT = "exit_report"
    SEMI_ANNUAL = "semi_annual"
    CURRENT = "current"
    WITHDRAWAL = "withdrawal"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RegADocument:
    """Structured representation of a Reg A XML submission at review depth."""

    submission_type: str | None
    kind: RegAKind
    live_test_flag: str | None
    filer_ciks: tuple[str, ...]
    issuer_name: str | None
    issuer_cik: str | None
    commission_file_number: str | None
    jurisdiction: str | None
    tier: str | None
    total_aggregate_offering: str | None
    has_summary_block: bool
    has_certification: bool


__all__ = ["RegADocument", "RegAKind"]
