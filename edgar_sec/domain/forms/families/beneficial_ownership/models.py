from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.domain.forms.common.signatures import SignatureBlock


class EvidenceState(StrEnum):
    VALUE = "value"
    BLANK = "blank"
    CHECKED = "checked"
    UNCHECKED = "unchecked"
    UNCLEAR = "unclear"


@dataclass(frozen=True, slots=True)
class FieldExtraction:
    field_path: str
    start_offset: int
    end_offset: int
    source_text: str
    shared_source_group: str | None = None


@dataclass(frozen=True, slots=True)
class UnparsedSection:
    start_offset: int
    end_offset: int
    text: str
    role: str = "unparsed"


@dataclass(frozen=True, slots=True)
class CoverItemEvidence:
    number: int
    source_text: str
    value: str | None
    state: EvidenceState
    tag: str = ""
    label: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True, slots=True)
class ReportingPersonCover:
    items: tuple[CoverItemEvidence, ...]
    source_text: str = ""
    comment_content: str | None = None

    def first_item(self, target: int | str) -> CoverItemEvidence | None:
        if isinstance(target, int):
            return next((item for item in self.items if item.number == target), None)
        return next((item for item in self.items if item.tag == target), None)

    def item_by_number(self, number: int) -> CoverItemEvidence | None:
        return next((item for item in self.items if item.number == number), None)

    def item_by_tag(self, tag: str) -> CoverItemEvidence | None:
        return next((item for item in self.items if item.tag == tag), None)


@dataclass(frozen=True, slots=True)
class AddressDetails:
    raw_text: str
    street1: str | None = None
    street2: str | None = None
    city: str | None = None
    state_or_country: str | None = None
    zip_code: str | None = None


@dataclass(frozen=True, slots=True)
class IssuerMetadata:
    issuer_name: str | None = None
    issuer_cik: str | None = None
    issuer_address: AddressDetails | None = None
    security_class: str | None = None
    cusip: str | None = None
    event_date: str | None = None
    notice_contact: str | None = None
    notice_phone: str | None = None
    notice_address: AddressDetails | None = None
    source_text: str = ""


@dataclass(frozen=True, slots=True)
class NarrativeField:
    tag: str
    value: str
    start_offset: int
    end_offset: int
    source_text: str
    shared_source_group: str | None = None


@dataclass(frozen=True, slots=True)
class NarrativeItem:
    number: int
    heading: str
    text: str
    start_offset: int
    end_offset: int
    raw_heading: str = ""
    parsed_fields: tuple[NarrativeField, ...] = ()


@dataclass(frozen=True, slots=True)
class BeneficialOwnershipDocument:
    issuer: IssuerMetadata
    reporting_persons: tuple[ReportingPersonCover, ...]
    narrative_items: tuple[NarrativeItem, ...] = ()
    signature_block: SignatureBlock | None = None
    signature_text: str | None = None
    submission_type: str = "SCHEDULE 13D"
    form_family: str = "13D"
    rule_designation: str | None = None
    previous_accession_number: str | None = None
    residual_text: str = ""
    diagnostics: tuple[str, ...] = ()
    source_length: int = 0
    field_extractions: tuple[FieldExtraction, ...] = ()
    unparsed_sections: tuple[UnparsedSection, ...] = ()

    @property
    def items1_to_7(self) -> tuple[NarrativeItem, ...]:
        return tuple(item for item in self.narrative_items if item.number <= 7)


__all__ = [
    "AddressDetails",
    "BeneficialOwnershipDocument",
    "CoverItemEvidence",
    "EvidenceState",
    "FieldExtraction",
    "IssuerMetadata",
    "NarrativeField",
    "NarrativeItem",
    "ReportingPersonCover",
    "UnparsedSection",
]
