"""Domain dataclasses for SEC Form N-PX filings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProxyVoteRow:
    """One proxy vote row of the N-PX proxy voting record document."""

    issuer_name: str
    meeting_date: str
    vote_description: str
    cusip: str | None = None
    isin: str | None = None
    figi: str | None = None
    category_types: tuple[str, ...] = ()
    vote_source: str | None = None
    shares_voted: str | None = None
    shares_on_loan: str | None = None
    how_voted: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FormNPxDocument:
    """Structured domain representation of a Form N-PX filing."""

    submission_type: str
    vote_rows: tuple[ProxyVoteRow, ...]
    registrant_type: str | None = None
    period_of_report: str | None = None
    year_or_quarter: str | None = None
    report_calendar_year: str | None = None
    reporting_person_name: str | None = None
    report_type: str | None = None
    file_number: str | None = None
    lei_number: str | None = None
    investment_company_type: str | None = None
    series_count: int | None = None
    other_included_managers_count: int | None = None


__all__ = [
    "FormNPxDocument",
    "ProxyVoteRow",
]
