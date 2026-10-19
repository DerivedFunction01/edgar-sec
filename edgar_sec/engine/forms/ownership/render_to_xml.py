"""XML document generation for SEC ownership forms."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.ownership.taxonomy import OWNERSHIP_STATE_CODES
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.document_processing.outputs import HandlerOutput, HandlerSidecar
from edgar_sec.engine.forms.ownership.securities import (
    DerivativeTransaction,
    NonDerivativeTransaction,
    parse_table_i_rows,
    parse_table_ii_rows,
)
from edgar_sec.engine.forms.ownership.footnotes import parse_footnotes
from edgar_sec.domain.forms.families.ownership.models import OwnershipMetadata
from edgar_sec.engine.forms.common.numbers import (
    normalize_schema_decimal,
    normalize_schema_number,
)
from edgar_sec.engine.forms.common.extraction import (
    FieldKind,
    FieldSpec,
    extract_value,
    normalize_record_fields,
)
from edgar_sec.engine.forms.common.dates import (
    external_reference_year,
    normalize_iso_date,
    resolve_reference_year,
)
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections
from edgar_sec.engine.forms.ownership.metadata_parser import parse_metadata
from edgar_sec.engine.forms.ownership.sections import (
    OwnershipSections,
    partition_ownership_tables,
)

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext


def _add_text_elem(
    parent: ET.Element,
    tag: str,
    text: str | None,
    reference_year: int | None = None,
) -> ET.Element:
    if text is None:
        return ET.Element(tag)
    value = (
        normalize_iso_date(
            text,
            reference_year,
            allow_month_year=tag == "periodOfReport",
        )
        if tag in {"periodOfReport", "dateOfOriginalSubmission", "signatureDate"}
        else text
    )
    if value is None:
        return ET.Element(tag)
    elem = ET.SubElement(parent, tag)
    elem.text = value
    return elem


def _add_valued_elem(
    parent: ET.Element,
    tag: str,
    value: str | None,
    reference_year: int | None = None,
) -> ET.Element:
    if value is None:
        return ET.Element(tag)
    if tag in {
        "transactionShares",
        "sharesOwnedFollowingTransaction",
        "underlyingSecurityShares",
    }:
        normalized = normalize_schema_number(
            value, integer=True, allow_integral_decimal=True
        ) or normalize_schema_decimal(value)
    elif tag in {"transactionPricePerShare", "conversionOrExercisePrice"}:
        normalized = normalize_schema_decimal(value)
    elif tag in {"transactionDate", "exerciseDate", "expirationDate"}:
        normalized = normalize_iso_date(value, reference_year)
    else:
        normalized = value
    if normalized is None:
        return ET.Element(tag)
    elem = ET.SubElement(parent, tag)
    val_elem = ET.SubElement(elem, "value")
    val_elem.text = normalized
    return elem


def _build_issuer_xml(root: ET.Element, metadata: OwnershipMetadata) -> None:
    issuer_el = ET.SubElement(root, "issuer")
    _add_text_elem(issuer_el, "issuerTradingSymbol", metadata.issuer.trading_symbol)


def _build_owner_xml(root: ET.Element, metadata: OwnershipMetadata) -> None:
    owner_el = ET.SubElement(root, "reportingOwner")
    ET.SubElement(owner_el, "reportingOwnerId")

    if any(
        (
            metadata.reporting_owner.street,
            metadata.reporting_owner.city,
            metadata.reporting_owner.state,
            metadata.reporting_owner.country,
            metadata.reporting_owner.zip_code,
        )
    ):
        addr_el = ET.SubElement(owner_el, "reportingOwnerAddress")
        _add_text_elem(
            addr_el,
            "rptOwnerNonUSAddressFlag",
            "1" if metadata.reporting_owner.country else "0",
        )
        _add_text_elem(addr_el, "rptOwnerStreet1", metadata.reporting_owner.street)
        _add_text_elem(addr_el, "rptOwnerCity", metadata.reporting_owner.city)
        _add_text_elem(addr_el, "rptOwnerState", metadata.reporting_owner.state)
        _add_text_elem(addr_el, "rptOwnerCountry", metadata.reporting_owner.country)
        _add_text_elem(addr_el, "rptOwnerZipCode", metadata.reporting_owner.zip_code)

    rel_el = ET.SubElement(owner_el, "reportingOwnerRelationship")
    _add_text_elem(
        rel_el, "isDirector", "1" if metadata.reporting_owner.is_director else "0"
    )
    _add_text_elem(
        rel_el, "isOfficer", "1" if metadata.reporting_owner.is_officer else "0"
    )
    _add_text_elem(
        rel_el,
        "isTenPercentOwner",
        "1" if metadata.reporting_owner.is_ten_percent_owner else "0",
    )
    _add_text_elem(rel_el, "isOther", "1" if metadata.reporting_owner.is_other else "0")
    if metadata.reporting_owner.officer_title:
        _add_text_elem(rel_el, "officerTitle", metadata.reporting_owner.officer_title)


def _build_non_derivative_xml(
    root: ET.Element,
    rows: list[NonDerivativeTransaction],
    reference_year: int | None,
    document_type: str,
) -> None:
    table_el = ET.SubElement(root, "nonDerivativeTable")
    for r in rows:
        is_holding = (
            document_type.startswith("3/")
            or document_type == "3"
            or (not r.transaction_date and not r.transaction_code)
        )
        tx_el = ET.SubElement(
            table_el,
            "nonDerivativeHolding" if is_holding else "nonDerivativeTransaction",
        )
        _add_valued_elem(tx_el, "securityTitle", r.security_title)
        if r.transaction_date and not is_holding:
            _add_valued_elem(
                tx_el, "transactionDate", r.transaction_date, reference_year
            )
        if r.transaction_code and not is_holding:
            coding_el = ET.SubElement(tx_el, "transactionCoding")
            _add_text_elem(coding_el, "transactionFormType", document_type[0])
            _add_text_elem(coding_el, "transactionCode", r.transaction_code)
            _add_text_elem(
                coding_el,
                "equitySwapInvolved",
                "1" if r.equity_swap_involved else "0",
            )
        if not is_holding and (
            r.shares_amount is not None
            or r.price_per_share is not None
            or r.acquired_disposed_code
        ):
            amounts_el = ET.SubElement(tx_el, "transactionAmounts")
            _add_valued_elem(amounts_el, "transactionShares", r.shares_amount)
            _add_valued_elem(amounts_el, "transactionPricePerShare", r.price_per_share)
            _add_valued_elem(
                amounts_el,
                "transactionAcquiredDisposedCode",
                r.acquired_disposed_code,
            )
        shares_owned = r.shares_owned_following
        if shares_owned is None and is_holding:
            shares_owned = r.shares_amount
        if shares_owned is not None:
            post_el = ET.SubElement(tx_el, "postTransactionAmounts")
            _add_valued_elem(post_el, "sharesOwnedFollowingTransaction", shares_owned)
        if r.direct_or_indirect:
            own_el = ET.SubElement(tx_el, "ownershipNature")
            _add_valued_elem(own_el, "directOrIndirectOwnership", r.direct_or_indirect)
            if r.nature_of_ownership:
                _add_valued_elem(own_el, "natureOfOwnership", r.nature_of_ownership)


def _build_derivative_xml(
    root: ET.Element,
    rows: list[DerivativeTransaction],
    reference_year: int | None,
    document_type: str,
) -> None:
    table_el = ET.SubElement(root, "derivativeTable")
    for r in rows:
        is_holding = (
            document_type.startswith("3/")
            or document_type == "3"
            or (not r.transaction_date and not r.transaction_code)
        )
        tx_el = ET.SubElement(
            table_el,
            "derivativeHolding" if is_holding else "derivativeTransaction",
        )
        _add_valued_elem(tx_el, "securityTitle", r.security_title)
        if r.conversion_or_exercise_price is not None:
            _add_valued_elem(
                tx_el,
                "conversionOrExercisePrice",
                r.conversion_or_exercise_price,
            )
        if r.transaction_date and not is_holding:
            _add_valued_elem(
                tx_el, "transactionDate", r.transaction_date, reference_year
            )
        if r.transaction_code and not is_holding:
            coding_el = ET.SubElement(tx_el, "transactionCoding")
            _add_text_elem(coding_el, "transactionFormType", document_type[0])
            _add_text_elem(coding_el, "transactionCode", r.transaction_code)
            _add_text_elem(
                coding_el,
                "equitySwapInvolved",
                "1" if r.equity_swap_involved else "0",
            )
        if r.exercisable_date or r.expiration_date:
            exp_el = ET.SubElement(tx_el, "exerciseDateAndExpirationDate")
            if r.exercisable_date:
                _add_valued_elem(
                    exp_el, "exerciseDate", r.exercisable_date, reference_year
                )
            if r.expiration_date:
                _add_valued_elem(
                    exp_el, "expirationDate", r.expiration_date, reference_year
                )
        if r.underlying_security_title or r.underlying_shares_amount is not None:
            under_el = ET.SubElement(tx_el, "underlyingSecurity")
            _add_valued_elem(
                under_el,
                "underlyingSecurityTitle",
                r.underlying_security_title,
            )
            _add_valued_elem(
                under_el,
                "underlyingSecurityShares",
                r.underlying_shares_amount,
            )
        shares_owned = r.derivative_shares_owned_following
        if shares_owned is None and is_holding:
            shares_owned = r.shares_amount
        if shares_owned is not None:
            post_el = ET.SubElement(tx_el, "postTransactionAmounts")
            _add_valued_elem(
                post_el,
                "sharesOwnedFollowingTransaction",
                shares_owned,
            )
        if r.direct_or_indirect:
            own_el = ET.SubElement(tx_el, "ownershipNature")
            _add_valued_elem(own_el, "directOrIndirectOwnership", r.direct_or_indirect)


def _unparsed_section_records(sections: OwnershipSections) -> list[dict[str, object]]:
    records = []
    for sec in sections.unparsed:
        raw_html = getattr(sec.raw_node, "html", None)
        raw_str = raw_html() if callable(raw_html) else str(raw_html or "")
        records.append(
            {
                "role": str(sec.role),
                "content_type": "text/html",
                "content": raw_str,
                "table_index": sec.table_index,
            }
        )
    return records


def render_ownership_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> bytes | HandlerOutput:
    """Transform ownership filing text into SEC ownership XML."""
    stripped = raw_bytes.strip()
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<ownershipDocument"):
        return raw_bytes

    text = raw_bytes.decode("utf-8", errors="replace")
    sections = partition_ownership_tables(text)
    external_year = (
        external_reference_year(
            getattr(context, "report_date", None),
            getattr(context, "filing_date", None),
        )
        if context is not None
        else None
    )
    if (
        sections.boxes_1_to_7 is None
        and sections.table_i is None
        and sections.table_ii is None
    ):
        from edgar_sec.engine.forms.ownership.ascii_parser import parse_ascii_form4

        ascii_secs = parse_ascii_form4(text, reference_year=external_year)
        if ascii_secs is not None:
            sections = ascii_secs

    metadata = parse_metadata(
        sections.boxes_1_to_7,
        sections.signatures,
        reference_year=external_year,
    )
    doc_type = (context.family if context and context.family else "4").upper()
    if doc_type not in {"3", "3/A", "4", "4/A", "5", "5/A"}:
        doc_type = "4"
    if metadata.period.is_amendment and not doc_type.endswith("/A"):
        doc_type = f"{doc_type}/A"
    source_period = metadata.period.period_of_report or metadata.period.date_of_original
    parser_year = resolve_reference_year(
        getattr(context, "report_date", None) if context is not None else None,
        getattr(context, "filing_date", None) if context is not None else None,
        (source_period,),
    )
    form3 = doc_type.startswith("3")
    table_i_rows = parse_table_i_rows(
        sections.table_i, reference_year=parser_year, holding_only=form3
    )
    table_ii_rows = parse_table_ii_rows(
        sections.table_ii, reference_year=parser_year, holding_only=form3
    )
    footnotes = parse_footnotes(sections.footnotes)

    root = ET.Element("ownershipDocument")
    _add_text_elem(root, "documentType", doc_type)
    period = metadata.period.period_of_report
    if not period and metadata.period.date_of_original:
        period = metadata.period.date_of_original
    if not period:
        tx_dates = [r.transaction_date for r in table_i_rows if r.transaction_date] + [
            r.transaction_date for r in table_ii_rows if r.transaction_date
        ]
        if tx_dates:
            period = tx_dates[0]
    tx_dates = tuple(row.transaction_date for row in (*table_i_rows, *table_ii_rows))
    reference_year = resolve_reference_year(
        getattr(context, "report_date", None) if context is not None else None,
        getattr(context, "filing_date", None) if context is not None else None,
        (period, *tx_dates),
    )
    unresolved_scalars: list[dict[str, object]] = []

    metadata_period, period_results = normalize_record_fields(
        metadata.period,
        (
            FieldSpec(
                "periodOfReport",
                FieldKind.DATE,
                source_attribute="period_of_report",
                allow_month_year=True,
            ),
            FieldSpec(
                "dateOfOriginalSubmission",
                FieldKind.DATE,
                source_attribute="date_of_original",
            ),
        ),
        reference_year,
    )
    for result in period_results:
        if record := result.unresolved_record():
            unresolved_scalars.append(record)
    signature_date = extract_value(
        metadata.signature_date,
        FieldSpec("signatureDate", FieldKind.DATE),
        reference_year=reference_year,
    )
    if record := signature_date.unresolved_record():
        unresolved_scalars.append(record)
    metadata = replace(
        metadata,
        period=metadata_period,
        signature_date=signature_date.value,
    )

    table_i_normalized: list[NonDerivativeTransaction] = []
    for row in table_i_rows:
        normalized, results = normalize_record_fields(
            row,
            (
                FieldSpec(
                    "transactionDate",
                    FieldKind.DATE,
                    source_attribute="transaction_date",
                ),
            ),
            reference_year=reference_year,
        )
        table_i_normalized.append(normalized)
        unresolved_scalars.extend(
            record
            for result in results
            if (record := result.unresolved_record()) is not None
        )
    table_i_rows = table_i_normalized

    table_ii_normalized: list[DerivativeTransaction] = []
    for row in table_ii_rows:
        normalized, results = normalize_record_fields(
            row,
            (
                FieldSpec(
                    "transactionDate",
                    FieldKind.DATE,
                    source_attribute="transaction_date",
                ),
                FieldSpec(
                    "exerciseDate",
                    FieldKind.DATE,
                    source_attribute="exercisable_date",
                ),
                FieldSpec(
                    "expirationDate",
                    FieldKind.DATE,
                    source_attribute="expiration_date",
                ),
            ),
            reference_year,
        )
        table_ii_normalized.append(normalized)
        unresolved_scalars.extend(
            record
            for result in results
            if (record := result.unresolved_record()) is not None
        )
    table_ii_rows = table_ii_normalized

    owner = metadata.reporting_owner
    state_result = extract_value(
        owner.state,
        FieldSpec(
            "rptOwnerState",
            FieldKind.JURISDICTION,
            allowed_values=OWNERSHIP_STATE_CODES,
        ),
    )
    country_result = extract_value(
        owner.country,
        FieldSpec(
            "rptOwnerCountry",
            FieldKind.JURISDICTION,
            allowed_values=EDGAR_JURISDICTION_CODES - OWNERSHIP_STATE_CODES,
        ),
    )
    for result in (state_result, country_result):
        if record := result.unresolved_record():
            unresolved_scalars.append(record)
    metadata = replace(
        metadata,
        reporting_owner=replace(
            owner,
            state=state_result.value,
            country=country_result.value,
        ),
    )
    period = metadata.period.period_of_report or metadata.period.date_of_original
    _add_text_elem(root, "periodOfReport", period, reference_year)
    if metadata.period.is_amendment and metadata.period.date_of_original:
        _add_text_elem(
            root,
            "dateOfOriginalSubmission",
            metadata.period.date_of_original,
            reference_year,
        )

    _build_issuer_xml(root, metadata)
    _build_owner_xml(root, metadata)
    _build_non_derivative_xml(root, table_i_rows, reference_year, doc_type)
    _build_derivative_xml(root, table_ii_rows, reference_year, doc_type)

    if footnotes:
        fn_container = ET.SubElement(root, "footnotes")
        for fn_id, fn_text in sorted(footnotes.items()):
            fn_el = ET.SubElement(fn_container, "footnote")
            fn_el.attrib["id"] = f"F{fn_id}"
            fn_el.text = fn_text

    if metadata.signature_name or metadata.signature_date:
        sig_el = ET.SubElement(root, "ownerSignature")
        _add_text_elem(sig_el, "signatureName", metadata.signature_name)
        _add_text_elem(sig_el, "signatureDate", metadata.signature_date, reference_year)

    ET.indent(root, space="    ")
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    unparsed_records = [*unresolved_scalars, *_unparsed_section_records(sections)]
    if form3:
        for role, section in (
            ("non_derivative_table", sections.table_i),
            ("derivative_table", sections.table_ii),
        ):
            parsed_rows = (
                table_i_rows if role == "non_derivative_table" else table_ii_rows
            )
            if section is not None and section.raw_node is not None and not parsed_rows:
                raw_html = getattr(section.raw_node, "html", None)
                raw_str = raw_html() if callable(raw_html) else str(raw_html or "")
                unparsed_records.append(
                    {
                        "role": role,
                        "content_type": "text/html",
                        "content": raw_str,
                    }
                )
    if unparsed_records:
        return HandlerOutput(
            content=xml_bytes,
            sidecars=(
                HandlerSidecar(
                    "unparsed_sections.json",
                    serialize_unparsed_sections(unparsed_records),
                ),
            ),
        )
    return xml_bytes


__all__ = [
    "render_ownership_to_xml",
]
