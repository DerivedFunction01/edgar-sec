"""Domain models for SEC submissions metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edgar_sec.domain.identity import Cik


@dataclass(frozen=True, slots=True)
class Address:
    street1: str | None = None
    street2: str | None = None
    city: str | None = None
    state_or_country: str | None = None
    zip_code: str | None = None
    state_or_country_description: str | None = None
    country: str | None = None
    country_code: str | None = None
    foreign_state_territory: str | None = None
    is_foreign_location: bool | None = None


@dataclass(frozen=True, slots=True)
class FormerName:
    name: str
    from_date: str | None = None
    to_date: str | None = None


@dataclass(frozen=True, slots=True)
class Listing:
    ticker: str
    exchange: str


@dataclass(frozen=True, slots=True)
class FilingRecord:
    accession_number: str | None = None
    accession_number_normalized: str | None = None
    filing_date: str | None = None
    report_date: str | None = None
    acceptance_datetime: str | None = None
    act: str | None = None
    form: str | None = None
    file_number: str | None = None
    film_number: str | None = None
    items: tuple[str, ...] = ()
    core_type: str | None = None
    size: int | None = None
    is_xbrl: bool | None = None
    is_inline_xbrl: bool | None = None
    is_xbrl_numeric: bool | None = None
    primary_document: str | None = None
    primary_doc_description: str | None = None
    archive_url: str | None = None
    source_section: str = ""
    source_file: str = ""
    source_array_index: int = 0


@dataclass(frozen=True, slots=True)
class EntityProfile:
    cik: Cik
    name: str
    entity_type: str | None = None
    sic_code: str | None = None
    sic_description: str | None = None
    owner_org: str | None = None
    filer_category: str | None = None
    ein: str | None = None
    lei: str | None = None
    phone: str | None = None
    website: str | None = None
    investor_website: str | None = None
    description: str | None = None
    state_of_incorporation: str | None = None
    state_of_incorporation_description: str | None = None
    fiscal_year_end: str | None = None
    owner_exists: bool | None = None
    issuer_exists: bool | None = None
    former_names: tuple[FormerName, ...] = ()
    listings: tuple[Listing, ...] = ()
    mailing_address: Address | None = None
    business_address: Address | None = None


@dataclass(frozen=True, slots=True)
class SubmissionsAggregate:
    cik: Cik
    profile: EntityProfile
    filings: tuple[FilingRecord, ...]
    anomalies: tuple[dict[str, Any], ...] = ()
    extra_fields: str | None = None


__all__ = [
    "Address",
    "EntityProfile",
    "FilingRecord",
    "FormerName",
    "Listing",
    "SubmissionsAggregate",
]
