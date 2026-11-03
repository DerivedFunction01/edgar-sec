"""Domain dataclasses for SEC Form N-MFP filings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NMfpSecurity:
    """One portfolio security row of a current-generation N-MFP filing."""

    issuer_name: str
    title: str
    cusip: str
    lei: str | None = None
    isin: str | None = None
    investment_category: str | None = None
    maturity_date_wam: str | None = None
    maturity_date_wal: str | None = None
    value_including_support: str | None = None
    percent_of_net_assets: str | None = None
    daily_liquid_asset: str | None = None
    weekly_liquid_asset: str | None = None
    illiquid: str | None = None


@dataclass(frozen=True, slots=True)
class FormNMfpDocument:
    """Structured domain representation of a Form N-MFP filing."""

    submission_type: str
    securities: tuple[NMfpSecurity, ...]
    generation: int | None = None
    report_date: str | None = None
    registrant_name: str | None = None
    registrant_cik: str | None = None
    series_name: str | None = None
    series_id: str | None = None
    series_lei: str | None = None
    class_count: int = 0


__all__ = [
    "FormNMfpDocument",
    "NMfpSecurity",
]
