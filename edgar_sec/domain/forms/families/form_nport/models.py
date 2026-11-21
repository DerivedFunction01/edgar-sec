"""Domain dataclasses for SEC Form N-PORT filings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NPortInvestment:
    """One investment row of the N-PORT schedule of investments."""

    name: str
    title: str
    cusip: str
    lei: str | None = None
    isin: str | None = None
    balance: str | None = None
    units: str | None = None
    currency_code: str | None = None
    value_usd: str | None = None
    percent_value: str | None = None
    payoff_profile: str | None = None
    asset_category: str | None = None
    issuer_category: str | None = None
    investment_country: str | None = None
    is_restricted: str | None = None
    fair_value_level: str | None = None


@dataclass(frozen=True, slots=True)
class FormNPortDocument:
    """Structured domain representation of a Form N-PORT filing."""

    submission_type: str
    registrant_name: str
    investments: tuple[NPortInvestment, ...]
    filer_cik: str | None = None
    is_confidential: str | None = None
    registrant_file_number: str | None = None
    registrant_cik: str | None = None
    registrant_lei: str | None = None
    series_name: str | None = None
    series_lei: str | None = None
    report_period_end: str | None = None
    report_period_date: str | None = None
    is_final_filing: str | None = None
    total_assets: str | None = None
    total_liabilities: str | None = None
    net_assets: str | None = None


__all__ = [
    "FormNPortDocument",
    "NPortInvestment",
]
