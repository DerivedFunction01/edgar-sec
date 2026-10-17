"""Domain models and schemas for SEC Form 4 ownership filings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReportingOwner:
    name: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    is_director: bool = False
    is_officer: bool = False
    is_ten_percent_owner: bool = False
    is_other: bool = False
    officer_title: str | None = None
    irs_number: str | None = None


@dataclass(frozen=True, slots=True)
class Issuer:
    name: str | None = None
    trading_symbol: str | None = None
    irs_number: str | None = None


@dataclass(frozen=True, slots=True)
class FilingPeriod:
    period_of_report: str | None = None
    is_amendment: bool = False
    date_of_original: str | None = None


@dataclass(frozen=True, slots=True)
class Form4Metadata:
    issuer: Issuer
    reporting_owner: ReportingOwner
    period: FilingPeriod
    signature_name: str | None = None
    signature_date: str | None = None


VALID_TRANSACTION_CODES: frozenset[str] = frozenset(
    {
        "P",
        "S",
        "A",
        "D",
        "F",
        "I",
        "M",
        "C",
        "E",
        "H",
        "O",
        "X",
        "G",
        "L",
        "W",
        "Z",
        "J",
        "U",
        "K",
    }
)

__all__ = [
    "FilingPeriod",
    "Form4Metadata",
    "Issuer",
    "ReportingOwner",
    "VALID_TRANSACTION_CODES",
]
