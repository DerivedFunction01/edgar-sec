"""Domain dataclasses for SEC Form 13F filings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ManagerAddress:
    """Mailing address of the institutional investment manager."""

    street1: str
    street2: str | None
    city: str
    state_or_country: str
    zip_code: str | None


@dataclass(frozen=True, slots=True)
class InfoTableRow:
    """One holding row of the 13F information table.

    ``value`` is in dollars (spec v1.7, effective 2023-01-03).
    """

    name_of_issuer: str
    title_of_class: str
    cusip: str
    value: int | None
    shares_or_principal: int | None
    amount_type: str | None
    investment_discretion: str | None
    voting_sole: int | None
    voting_shared: int | None
    voting_none: int | None
    figi: str | None = None
    put_call: str | None = None
    other_managers: str | None = None


@dataclass(frozen=True, slots=True)
class Form13FDocument:
    """Complete structured domain representation of a Form 13F filing."""

    submission_type: str
    manager_name: str
    holdings: tuple[InfoTableRow, ...]
    live_test_flag: str | None = None
    period_of_report: str | None = None
    report_calendar_or_quarter: str | None = None
    is_amendment: bool = False
    amendment_number: int | None = None
    amendment_type: str | None = None
    report_type: str | None = None
    form13f_file_number: str | None = None
    crd_number: str | None = None
    sec_file_number: str | None = None
    manager_address: ManagerAddress | None = None
    other_included_managers_count: int | None = None
    table_entry_total: int | None = None
    table_value_total: int | None = None
    is_confidential_omitted: bool | None = None


__all__ = [
    "Form13FDocument",
    "InfoTableRow",
    "ManagerAddress",
]
