"""Domain models and schemas for SEC Form 144 filings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IssuerInformation:
    cik: str | None = None
    name: str | None = None
    sec_file_number: str | None = None
    street1: str | None = None
    street2: str | None = None
    city: str | None = None
    state_or_country: str | None = None
    zip_code: str | None = None
    contact_phone: str | None = None


@dataclass(frozen=True, slots=True)
class ReportingPerson:
    name: str | None = None
    street1: str | None = None
    street2: str | None = None
    city: str | None = None
    state_or_country: str | None = None
    zip_code: str | None = None
    relationships: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BrokerDetails:
    name: str | None = None
    street1: str | None = None
    street2: str | None = None
    city: str | None = None
    state_or_country: str | None = None
    zip_code: str | None = None
    file_number: str | None = None


@dataclass(frozen=True, slots=True)
class ProposedSaleItem:
    class_title: str | None = None
    broker: BrokerDetails | None = None
    units_to_be_sold: int | str | None = None
    aggregate_market_value: str | float | int | None = None
    units_outstanding: int | str | None = None
    approx_sale_date: str | None = None
    exchange_name: str | None = None


@dataclass(frozen=True, slots=True)
class TableISecurityItem:
    class_title: str | None = None
    acquired_date: str | None = None
    nature_of_acquisition: str | None = None
    donor_or_seller_name: str | None = None
    is_gift: bool = False
    amount_acquired: int | str | None = None
    payment_date: str | None = None
    nature_of_payment: str | None = None


@dataclass(frozen=True, slots=True)
class TableIISecuritySoldItem:
    seller_name: str | None = None
    seller_address: str | None = None
    class_title: str | None = None
    sale_date: str | None = None
    amount_sold: int | str | None = None
    gross_proceeds: str | float | int | None = None


@dataclass(frozen=True, slots=True)
class NoticeSignature:
    notice_date: str | None = None
    plan_adoption_dates: tuple[str, ...] = ()
    signature: str | None = None


@dataclass(frozen=True, slots=True)
class Form144Document:
    issuer: IssuerInformation
    reporting_person: ReportingPerson
    proposed_sale: ProposedSaleItem
    securities_to_be_sold: tuple[TableISecurityItem, ...] = ()
    nothing_to_report_past_3_months: bool = True
    securities_sold_past_3_months: tuple[TableIISecuritySoldItem, ...] = ()
    remarks: str | None = None
    signature: NoticeSignature | None = None


__all__ = [
    "BrokerDetails",
    "Form144Document",
    "IssuerInformation",
    "NoticeSignature",
    "ProposedSaleItem",
    "ReportingPerson",
    "TableISecurityItem",
    "TableIISecuritySoldItem",
]
