"""Versioned data models for SEC cover-page semantic extraction and layout rendering."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Security12b:
    """A registered security under Section 12(b) of the 1934 Act."""

    title_of_class: str
    trading_symbol: str | None = None
    exchange: str | None = None
    registrant: str | None = None


@dataclass(frozen=True, slots=True)
class RegistrantEntry:
    """A single legal entity in a joint/multi-registrant SEC filing (e.g. utility groups)."""

    company_name: str
    cik: str | None = None
    irs_ein: str | None = None
    state_of_incorporation: str | None = None
    commission_file_number: str | None = None
    principal_address: str | None = None
    phone_number: str | None = None
    is_target_entity: bool = False


@dataclass(frozen=True, slots=True)
class CheckboxDisclosures:
    """Status checkboxes and regulatory disclosure flags with strict tri-state era guards."""

    is_wksi: bool | None = None
    is_large_accelerated: bool | None = None
    is_accelerated_filer: bool | None = None
    is_non_accelerated: bool | None = None
    is_smaller_reporting_company: bool | None = None
    is_emerging_growth: bool | None = None
    is_shell_company: bool | None = None
    is_voluntary_filer: bool | None = None
    has_clawback_recovery: bool | None = None
    filed_all_reports_90_days: bool | None = None
    filed_interactive_data_405: bool | None = None


@dataclass(frozen=True, slots=True)
class CoverPageModel:
    """Normalized semantic model representing an SEC Form cover page (1994–2026)."""

    form: str
    company_name: str
    cik: str | None = None
    irs_ein: str | None = None
    state_of_incorporation: str | None = None
    commission_file_number: str | None = None
    fiscal_year_end: str | None = None

    # Location & Contact
    principal_address: str | None = None
    zip_code: str | None = None
    phone_number: str | None = None

    # Multi-Registrants & Securities
    co_registrants: tuple[RegistrantEntry, ...] = ()
    securities_12b: tuple[Security12b, ...] = ()
    shares_outstanding: str | None = None
    public_float: str | None = None

    # Status Checkboxes
    checkboxes: CheckboxDisclosures = field(default_factory=CheckboxDisclosures)

    # Auditor Disclosures (2021+)
    auditor_name: str | None = None
    auditor_location: str | None = None
    auditor_pcaob_id: str | None = None

    # Documents Incorporated by Reference Note
    incorporated_documents_note: str | None = None


__all__ = [
    "CheckboxDisclosures",
    "CoverPageModel",
    "RegistrantEntry",
    "Security12b",
]
