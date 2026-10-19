from __future__ import annotations

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    BeneficialOwnershipDocument,
    FieldExtraction,
    UnparsedSection,
)
from edgar_sec.domain.forms.common.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
)
from edgar_sec.engine.forms.beneficial_ownership.cover_value_diagnostics import (
    two_character_codes,
)
from edgar_sec.engine.forms.beneficial_ownership.vocabulary import (
    NARRATIVE_FIELDS,
    REPORTING_PERSON_FIELDS,
)

_ISSUER_FIELDS = (
    ("securitiesClassTitle", "issuer.security_class"),
    ("dateOfEvent", "issuer.event_date"),
)


def _fold_with_offsets(text: str) -> tuple[str, list[int], list[int]]:
    folded: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            if folded and folded[-1] == " ":
                ends[-1] = index + 1
            elif folded:
                folded.append(" ")
                starts.append(index)
                ends.append(index + 1)
            continue
        for part in char.casefold():
            folded.append(part)
            starts.append(index)
            ends.append(index + 1)
    if folded and folded[-1] == " ":
        folded.pop()
        starts.pop()
        ends.pop()
    return "".join(folded), starts, ends


def _find_span(
    source: str,
    value: str,
    start: int = 0,
    end: int | None = None,
) -> tuple[int, int] | None:
    if end is None:
        end = len(source)
    if start < 0 or end > len(source) or end < start:
        return None
    target = " ".join(value.split()).casefold()
    if not target:
        return None
    folded, starts, ends = _fold_with_offsets(source[start:end])
    found = folded.find(target)
    if found < 0:
        return None
    return start + starts[found], start + ends[found + len(target) - 1]


def _append_extraction(
    extractions: list[FieldExtraction],
    source: str,
    field_path: str,
    value: str | None,
    start: int,
    end: int,
    *,
    fallback: tuple[int, int] | None = None,
    shared_source_group: str | None = None,
) -> None:
    if not value:
        return
    span = _find_span(source, value, start, end)
    if span is None:
        span = fallback
    if span is None or not 0 <= span[0] < span[1] <= len(source):
        return
    extractions.append(
        FieldExtraction(
            field_path=field_path,
            start_offset=span[0],
            end_offset=span[1],
            source_text=source[span[0] : span[1]],
            shared_source_group=shared_source_group,
        )
    )


def _append_address_extractions(
    extractions: list[FieldExtraction],
    source: str,
    path: str,
    address: object | None,
    header_end: int,
) -> None:
    if address is None:
        return
    raw_text = getattr(address, "raw_text", "")
    raw_span = _find_span(source, raw_text, 0, header_end) if raw_text else None
    if raw_span is None:
        return
    region_start, region_end = raw_span
    cursor = region_start
    for source_name, output_name in (
        ("street1", "com:street1"),
        ("street2", "com:street2"),
        ("city", "com:city"),
        ("state_or_country", "com:stateOrCountry"),
        ("zip_code", "com:zipCode"),
    ):
        value = getattr(address, source_name, None)
        if not value:
            continue
        span = _find_span(source, value, cursor, region_end)
        if span is None:
            continue
        extractions.append(
            FieldExtraction(
                field_path=f"{path}.{output_name}",
                start_offset=span[0],
                end_offset=span[1],
                source_text=source[span[0] : span[1]],
            )
        )
        cursor = span[1]


def build_field_extractions(
    document: BeneficialOwnershipDocument,
    source_text: str,
    header_end: int,
) -> tuple[FieldExtraction, ...]:
    extractions: list[FieldExtraction] = []
    for output_name, attribute in _ISSUER_FIELDS:
        _append_extraction(
            extractions,
            source_text,
            f"formData.coverPageHeader.{output_name}",
            getattr(document.issuer, attribute.split(".", 1)[1]),
            0,
            header_end,
        )
    for path, value in (
        ("issuerInfo.issuerCIK", document.issuer.issuer_cik),
        ("issuerInfo.issuerName", document.issuer.issuer_name),
        ("issuerInfo.issuerCusips.issuerCusipNumber", document.issuer.cusip),
        (
            "authorizedPersons.notificationInfo.personName",
            document.issuer.notice_contact,
        ),
        (
            "authorizedPersons.notificationInfo.personPhoneNum",
            document.issuer.notice_phone,
        ),
    ):
        _append_extraction(
            extractions,
            source_text,
            f"formData.coverPageHeader.{path}",
            value,
            0,
            header_end,
        )
    _append_address_extractions(
        extractions,
        source_text,
        "formData.coverPageHeader.issuerInfo.address",
        document.issuer.issuer_address,
        header_end,
    )
    _append_address_extractions(
        extractions,
        source_text,
        "formData.coverPageHeader.authorizedPersons.notificationInfo.personAddress",
        document.issuer.notice_address,
        header_end,
    )

    for person_index, person in enumerate(document.reporting_persons, start=1):
        for item in person.items:
            if item.tag not in REPORTING_PERSON_FIELDS:
                continue
            if (
                item.tag == "memberOfGroup"
                and CANONICAL_CHECKED not in (item.value or "").upper()
            ):
                continue
            if item.tag in {
                "fundType",
                "typeOfReportingPerson",
            } and not two_character_codes(item.value):
                continue
            if item.tag in {"legalProceedings", "isAggregateExcludeShares"}:
                value = item.value
                if item.state.value == "checked":
                    value = CANONICAL_CHECKED
                elif item.state.value == "unchecked":
                    value = CANONICAL_UNCHECKED
            else:
                value = item.value
            _append_extraction(
                extractions,
                source_text,
                f"formData.reportingPersons.reportingPersonInfo[{person_index}].{item.tag}",
                value,
                item.start_offset or 0,
                item.end_offset or 0,
                fallback=(item.start_offset, item.end_offset)
                if item.start_offset is not None and item.end_offset is not None
                else None,
                shared_source_group=f"person-{person_index}-item-{item.number}",
            )
        if person.comment_content:
            evidence = person.first_item("typeOfReportingPerson")
            if evidence is not None:
                _append_extraction(
                    extractions,
                    source_text,
                    f"formData.reportingPersons.reportingPersonInfo[{person_index}].commentContent",
                    person.comment_content,
                    evidence.start_offset or 0,
                    evidence.end_offset or 0,
                    fallback=(evidence.start_offset, evidence.end_offset)
                    if evidence.start_offset is not None
                    and evidence.end_offset is not None
                    else None,
                    shared_source_group=f"person-{person_index}-item-{evidence.number}",
                )

    for item in document.narrative_items:
        items_name = "items1To10" if document.form_family == "13G" else "items1To7"
        if item.number in {2, 5}:
            for field in item.parsed_fields:
                extractions.append(
                    FieldExtraction(
                        field_path=(
                            f"formData.{items_name}.item{item.number}.{field.tag}"
                        ),
                        start_offset=field.start_offset,
                        end_offset=field.end_offset,
                        source_text=field.source_text,
                        shared_source_group=field.shared_source_group,
                    )
                )
            continue
        field = NARRATIVE_FIELDS.get(item.number, "commentText")
        _append_extraction(
            extractions,
            source_text,
            f"formData.{items_name}.item{item.number}.{field}",
            item.text,
            item.start_offset,
            item.end_offset,
            fallback=(item.start_offset, item.end_offset),
        )

    if document.signature_block and document.signature_text:
        signature_span = _find_span(source_text, document.signature_text)
        if signature_span is not None:
            signer_search_start = signature_span[0]
            for signer_index, signer in enumerate(
                document.signature_block.signatories, start=1
            ):
                signature_source_span = _find_span(
                    source_text,
                    signer.name,
                    signer_search_start,
                    signature_span[1],
                )
                if signature_source_span is not None:
                    signer_search_start = signature_source_span[1]
                signature_group = (
                    f"signature-{signer_index}"
                    if signature_source_span is not None
                    else "signature-block"
                )
                _append_extraction(
                    extractions,
                    source_text,
                    "formData.signatureInfo.signaturePerson"
                    f"[{signer_index}].signatureDetails.signature",
                    signer.name,
                    *(signature_source_span or signature_span),
                    fallback=signature_source_span or signature_span,
                    shared_source_group=signature_group,
                )
                _append_extraction(
                    extractions,
                    source_text,
                    "formData.signatureInfo.signaturePerson"
                    f"[{signer_index}].signatureDetails.date",
                    signer.date,
                    *signature_span,
                    shared_source_group="signature-date",
                )
                _append_extraction(
                    extractions,
                    source_text,
                    "formData.signatureInfo.signaturePerson"
                    f"[{signer_index}].signatureDetails.title",
                    signer.title,
                    *signature_span,
                    shared_source_group="signature-title",
                )
    return tuple(extractions)


def build_unparsed_sections(
    source_text: str,
    extractions: tuple[FieldExtraction, ...],
    narrative_items: tuple[object, ...] = (),
) -> tuple[UnparsedSection, ...]:
    covered = bytearray(len(source_text))
    for extraction in extractions:
        if 0 <= extraction.start_offset <= extraction.end_offset <= len(source_text):
            covered[extraction.start_offset : extraction.end_offset] = bytes([1]) * (
                extraction.end_offset - extraction.start_offset
            )

    sections: list[UnparsedSection] = []
    index = 0
    while index < len(source_text):
        if covered[index] or source_text[index].isspace():
            index += 1
            continue
        start = index
        while index < len(source_text) and not covered[index]:
            index += 1
        end = index
        while end > start and source_text[end - 1].isspace():
            end -= 1
        if end > start:
            item_number = next(
                (
                    item.number
                    for item in narrative_items
                    if item.number in {2, 5}
                    and item.start_offset <= start
                    and end <= item.end_offset
                ),
                None,
            )
            sections.append(
                UnparsedSection(
                    start,
                    end,
                    source_text[start:end],
                    role=f"item{item_number}.unparsed"
                    if item_number is not None
                    else "unparsed",
                )
            )
    return tuple(sections)


__all__ = ["build_field_extractions", "build_unparsed_sections"]
