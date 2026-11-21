"""Domain dataclasses for SEC Form D filings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IssuerAddress:
    """Mailing or physical address for an issuer or related entity."""

    street1: str
    street2: str | None
    city: str
    state_or_country: str
    state_or_country_desc: str | None
    zip_code: str | None


@dataclass(frozen=True, slots=True)
class PrimaryIssuer:
    """Core identity and jurisdiction details for the primary issuer."""

    cik: str
    entity_name: str
    address: IssuerAddress | None
    phone_number: str | None
    jurisdiction: str | None
    entity_type: str | None
    year_of_inc: str | None


@dataclass(frozen=True, slots=True)
class RelatedPerson:
    """Executive officer, director, or promoter related to the issuer."""

    first_name: str | None
    middle_name: str | None
    last_name: str | None
    address: IssuerAddress | None
    relationships: tuple[str, ...]
    clarification: str | None = None


@dataclass(frozen=True, slots=True)
class OfferingSalesAmounts:
    """Offering and sales totals and remaining balances."""

    total_offering_amount: float | None
    total_amount_sold: float | None
    total_remaining: float | None
    is_indefinite: bool = False


@dataclass(frozen=True, slots=True)
class Signatory:
    """Authorized representative signatory block."""

    issuer_name: str
    signature_name: str
    name_of_signer: str
    signature_title: str
    signature_date: str


@dataclass(frozen=True, slots=True)
class FormDDocument:
    """Complete structured domain representation of a Form D filing."""

    schema_version: str
    submission_type: str
    test_or_live: str
    primary_issuer: PrimaryIssuer
    related_persons: tuple[RelatedPerson, ...]
    offering_amounts: OfferingSalesAmounts | None
    signatures: tuple[Signatory, ...]
    industry_group: str | None = None
    federal_exemptions: tuple[str, ...] = ()


__all__ = [
    "FormDDocument",
    "IssuerAddress",
    "OfferingSalesAmounts",
    "PrimaryIssuer",
    "RelatedPerson",
    "Signatory",
]
