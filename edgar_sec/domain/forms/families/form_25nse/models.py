"""Domain dataclasses for SEC Form 25-NSE filings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExchangeFiler:
    """The exchange filing the removal notification (filed-by company)."""

    cik: str | None
    ccc: str | None
    entity_name: str | None


@dataclass(frozen=True, slots=True)
class IssuerAddress:
    """Address block of the issuer whose class of securities is removed."""

    street1: str | None
    street2: str | None
    city: str | None
    state_or_country_code: str | None
    zip_code: str | None


@dataclass(frozen=True, slots=True)
class RemovalIssuer:
    """The issuer whose class of securities is struck from listing."""

    cik: str | None
    entity_name: str | None
    file_number: str | None
    address: IssuerAddress | None
    telephone_number: str | None


@dataclass(frozen=True, slots=True)
class RemovalSignature:
    """Signature block of the exchange's authorized officer."""

    name: str | None
    title: str | None
    date: str | None


@dataclass(frozen=True, slots=True)
class Form25NseDocument:
    """Complete structured representation of a notification of removal."""

    schema_version: str | None
    exchange: ExchangeFiler
    issuer: RemovalIssuer
    description_class_security: str | None
    rule_provision: str | None
    signature: RemovalSignature


__all__ = [
    "ExchangeFiler",
    "Form25NseDocument",
    "IssuerAddress",
    "RemovalIssuer",
    "RemovalSignature",
]
