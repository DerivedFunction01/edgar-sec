"""XML document generation for SEC ownership forms."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.ownership.models import OwnershipMetadata
from edgar_sec.domain.forms.families.ownership.taxonomy import OWNERSHIP_STATE_CODES
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.document_processing.outputs import HandlerOutput, HandlerSidecar
from edgar_sec.engine.forms.common.dates import (
    external_reference_year,
    normalize_iso_date,
    resolve_reference_year,
)
from edgar_sec.engine.forms.common.extraction import (
    FieldKind,
    FieldSpec,
    add_field_element,
    build_scalar_evidence_record,
    constraint_issue,
    emit_field_value,
    extract_value,
    normalize_value,
)
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections
from edgar_sec.engine.forms.common.row_extraction import RowSpec, normalize_row_record
from edgar_sec.engine.forms.ownership.field_specs import OWNERSHIP_METADATA_FIELDS
from edgar_sec.engine.forms.ownership.footnotes import parse_footnotes
from edgar_sec.engine.forms.ownership.metadata_parser import parse_metadata
from edgar_sec.engine.forms.ownership.row_specs import (
    OWNERSHIP_TABLE_I_ROW_SPEC,
    OWNERSHIP_TABLE_II_ROW_SPEC,
)
from edgar_sec.engine.forms.ownership.table_common import (
    DerivativeTransaction,
    NonDerivativeTransaction,
)
from edgar_sec.engine.forms.ownership.table_i import parse_table_i_rows
from edgar_sec.engine.forms.ownership.table_ii import parse_table_ii_rows
from edgar_sec.engine.forms.ownership.sections import (
    OwnershipSections,
    partition_ownership_tables,
)

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext


def _add_field(
    parent: ET.Element,
    spec: FieldSpec,
    value: str | None,
    reference_year: int | None,
    unresolved: list[dict[str, object]],
    *,
    path: str | None = None,
) -> None:
    add_field_element(
        parent,
        spec,
        value,
        reference_year=reference_year,
        unresolved=unresolved,
        path=path,
    )


def _add_metadata_field(
    parent: ET.Element,
    tag: str,
    value: str | None,
    reference_year: int | None,
    unresolved: list[dict[str, object]],
) -> None:
    spec = OWNERSHIP_METADATA_FIELDS[tag]
    _add_field(parent, spec, value, reference_year, unresolved)


def _row_field(spec: RowSpec, name: str) -> FieldSpec:
    column = spec.column(name)
    if column is None:
        raise KeyError(name)
    return column.field


def _build_issuer_xml(
    root: ET.Element,
    metadata: OwnershipMetadata,
    reference_year: int | None,
    unresolved: list[dict[str, object]],
) -> None:
    issuer_el = ET.SubElement(root, "issuer")
    _add_metadata_field(
        issuer_el,
        "issuerTradingSymbol",
        metadata.issuer.trading_symbol,
        reference_year,
        unresolved,
    )


def _build_owner_xml(
    root: ET.Element,
    metadata: OwnershipMetadata,
    reference_year: int | None,
    unresolved: list[dict[str, object]],
) -> None:
    owner = metadata.reporting_owner
    owner_el = ET.SubElement(root, "reportingOwner")
    ET.SubElement(owner_el, "reportingOwnerId")

    if any(
        (
            owner.street,
            owner.city,
            owner.state,
            owner.country,
            owner.zip_code,
        )
    ):
        addr_el = ET.SubElement(owner_el, "reportingOwnerAddress")
        _add_metadata_field(
            addr_el,
            "rptOwnerNonUSAddressFlag",
            "1" if owner.country else "0",
            reference_year,
            unresolved,
        )
        for tag, value in (
            ("rptOwnerStreet1", owner.street),
            ("rptOwnerCity", owner.city),
            ("rptOwnerState", owner.state),
            ("rptOwnerCountry", owner.country),
            ("rptOwnerZipCode", owner.zip_code),
        ):
            _add_metadata_field(addr_el, tag, value, reference_year, unresolved)

    rel_el = ET.SubElement(owner_el, "reportingOwnerRelationship")
    for tag, value in (
        ("isDirector", "1" if owner.is_director else "0"),
        ("isOfficer", "1" if owner.is_officer else "0"),
        ("isTenPercentOwner", "1" if owner.is_ten_percent_owner else "0"),
        ("isOther", "1" if owner.is_other else "0"),
    ):
        _add_metadata_field(rel_el, tag, value, reference_year, unresolved)
    if owner.officer_title:
        _add_metadata_field(
            rel_el, "officerTitle", owner.officer_title, reference_year, unresolved
        )


def _resolve_row(
    row: object,
    spec: RowSpec,
    reference_year: int | None,
    unresolved: list[dict[str, object]],
    prefix: str,
) -> dict[str, str | None]:
    """Resolve a table row through the shared contract, recording unresolved values."""
    _, extraction = normalize_row_record(
        row,
        spec,
        reference_year=reference_year,
        path_prefix=prefix,
    )
    unresolved.extend(extraction.evidence())
    return extraction.normalized


def _emit(
    parent: ET.Element,
    spec: RowSpec,
    name: str,
    values: dict[str, str | None],
) -> None:
    value = values.get(name)
    if value is None:
        return
    emit_field_value(parent, _row_field(spec, name), value)


def _build_non_derivative_xml(
    root: ET.Element,
    rows: list[NonDerivativeTransaction],
    reference_year: int | None,
    document_type: str,
    unresolved: list[dict[str, object]],
) -> None:
    table_el = ET.SubElement(root, "nonDerivativeTable")
    for index, row in enumerate(rows):
        is_holding = (
            document_type.startswith("3/")
            or document_type == "3"
            or (not row.transaction_date and not row.transaction_code)
        )
        tx_el = ET.SubElement(
            table_el,
            "nonDerivativeHolding" if is_holding else "nonDerivativeTransaction",
        )
        spec = OWNERSHIP_TABLE_I_ROW_SPEC
        values = _resolve_row(
            row, spec, reference_year, unresolved, f"table_i[{index}]."
        )
        _emit(tx_el, spec, "security_title", values)
        if values["transaction_date"] is not None and not is_holding:
            _emit(tx_el, spec, "transaction_date", values)
        if values["transaction_code"] is not None and not is_holding:
            coding_el = ET.SubElement(tx_el, "transactionCoding")
            _add_metadata_field(
                coding_el,
                "transactionFormType",
                document_type[0],
                reference_year,
                unresolved,
            )
            _emit(coding_el, spec, "transaction_code", values)
            _add_metadata_field(
                coding_el,
                "equitySwapInvolved",
                "1" if row.equity_swap_involved else "0",
                reference_year,
                unresolved,
            )
        if not is_holding and (
            values["shares_amount"] is not None
            or values["price_per_share"] is not None
            or values["acquired_disposed_code"] is not None
        ):
            amounts_el = ET.SubElement(tx_el, "transactionAmounts")
            _emit(amounts_el, spec, "shares_amount", values)
            _emit(amounts_el, spec, "price_per_share", values)
            _emit(amounts_el, spec, "acquired_disposed_code", values)
        shares_owned = values["shares_owned_following"]
        if shares_owned is None and is_holding:
            shares_owned = values["shares_amount"]
        if shares_owned is not None:
            post_el = ET.SubElement(tx_el, "postTransactionAmounts")
            emit_field_value(
                post_el, _row_field(spec, "shares_owned_following"), shares_owned
            )
        if values["direct_or_indirect"] is not None:
            own_el = ET.SubElement(tx_el, "ownershipNature")
            _emit(own_el, spec, "direct_or_indirect", values)
            if values["nature_of_ownership"] is not None:
                _emit(own_el, spec, "nature_of_ownership", values)


def _build_derivative_xml(
    root: ET.Element,
    rows: list[DerivativeTransaction],
    reference_year: int | None,
    document_type: str,
    unresolved: list[dict[str, object]],
) -> None:
    table_el = ET.SubElement(root, "derivativeTable")
    for index, row in enumerate(rows):
        is_holding = (
            document_type.startswith("3/")
            or document_type == "3"
            or (not row.transaction_date and not row.transaction_code)
        )
        tx_el = ET.SubElement(
            table_el,
            "derivativeHolding" if is_holding else "derivativeTransaction",
        )
        spec = OWNERSHIP_TABLE_II_ROW_SPEC
        values = _resolve_row(
            row, spec, reference_year, unresolved, f"table_ii[{index}]."
        )
        _emit(tx_el, spec, "security_title", values)
        _emit(tx_el, spec, "conversion_or_exercise_price", values)
        if values["transaction_date"] is not None and not is_holding:
            _emit(tx_el, spec, "transaction_date", values)
        if values["transaction_code"] is not None and not is_holding:
            coding_el = ET.SubElement(tx_el, "transactionCoding")
            _add_metadata_field(
                coding_el,
                "transactionFormType",
                document_type[0],
                reference_year,
                unresolved,
            )
            _emit(coding_el, spec, "transaction_code", values)
            _add_metadata_field(
                coding_el,
                "equitySwapInvolved",
                "1" if row.equity_swap_involved else "0",
                reference_year,
                unresolved,
            )
        if (
            values["exercisable_date"] is not None
            or values["expiration_date"] is not None
        ):
            exp_el = ET.SubElement(tx_el, "exerciseDateAndExpirationDate")
            _emit(exp_el, spec, "exercisable_date", values)
            _emit(exp_el, spec, "expiration_date", values)
        if (
            values["underlying_security_title"] is not None
            or values["underlying_shares_amount"] is not None
        ):
            under_el = ET.SubElement(tx_el, "underlyingSecurity")
            _emit(under_el, spec, "underlying_security_title", values)
            _emit(under_el, spec, "underlying_shares_amount", values)
        shares_owned = values["derivative_shares_owned_following"]
        if shares_owned is None and is_holding:
            shares_owned = values["shares_amount"]
        if shares_owned is not None:
            post_el = ET.SubElement(tx_el, "postTransactionAmounts")
            emit_field_value(
                post_el,
                _row_field(spec, "derivative_shares_owned_following"),
                shares_owned,
            )
        if values["direct_or_indirect"] is not None:
            own_el = ET.SubElement(tx_el, "ownershipNature")
            _emit(own_el, spec, "direct_or_indirect", values)


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
    report_date = getattr(context, "report_date", None) if context is not None else None
    filing_date = getattr(context, "filing_date", None) if context is not None else None
    external_year = external_reference_year(report_date, filing_date)
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
    parser_year = resolve_reference_year(report_date, filing_date, (source_period,))
    form3 = doc_type.startswith("3")
    table_i_rows = parse_table_i_rows(
        sections.table_i, reference_year=parser_year, holding_only=form3
    )
    table_ii_rows = parse_table_ii_rows(
        sections.table_ii, reference_year=parser_year, holding_only=form3
    )
    footnotes = parse_footnotes(sections.footnotes)

    root = ET.Element("ownershipDocument")
    unresolved_scalars: list[dict[str, object]] = []
    _add_metadata_field(root, "documentType", doc_type, None, unresolved_scalars)
    period = metadata.period.period_of_report or metadata.period.date_of_original
    if not period:
        tx_dates = [r.transaction_date for r in table_i_rows if r.transaction_date] + [
            r.transaction_date for r in table_ii_rows if r.transaction_date
        ]
        if tx_dates:
            period = tx_dates[0]
    tx_dates = tuple(row.transaction_date for row in (*table_i_rows, *table_ii_rows))
    reference_year = resolve_reference_year(
        report_date, filing_date, (period, *tx_dates, metadata.signature_date)
    )

    period_spec = OWNERSHIP_METADATA_FIELDS["periodOfReport"]
    period_value = normalize_value(
        metadata.period.period_of_report, period_spec, reference_year
    )
    original_value = normalize_value(
        metadata.period.date_of_original,
        OWNERSHIP_METADATA_FIELDS["dateOfOriginalSubmission"],
        reference_year,
    )
    signature_value = normalize_value(
        metadata.signature_date,
        OWNERSHIP_METADATA_FIELDS["signatureDate"],
        reference_year,
    )
    for raw_value, spec, normalized in (
        (metadata.period.period_of_report, period_spec, period_value),
        (
            metadata.period.date_of_original,
            OWNERSHIP_METADATA_FIELDS["dateOfOriginalSubmission"],
            original_value,
        ),
        (
            metadata.signature_date,
            OWNERSHIP_METADATA_FIELDS["signatureDate"],
            signature_value,
        ),
    ):
        if normalized is None:
            if raw_value and raw_value.strip():
                record = build_scalar_evidence_record(
                    spec.path,
                    raw_value,
                    status="unresolved",
                    reference_year=reference_year,
                )
                if record is not None:
                    unresolved_scalars.append(record)
    metadata = replace(
        metadata,
        period=replace(
            metadata.period,
            period_of_report=period_value,
            date_of_original=original_value,
        ),
        signature_date=signature_value,
    )

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
    _add_metadata_field(
        root, "periodOfReport", period, reference_year, unresolved_scalars
    )
    if metadata.period.is_amendment and metadata.period.date_of_original:
        _add_metadata_field(
            root,
            "dateOfOriginalSubmission",
            metadata.period.date_of_original,
            reference_year,
            unresolved_scalars,
        )

    _build_issuer_xml(root, metadata, reference_year, unresolved_scalars)
    _build_owner_xml(root, metadata, reference_year, unresolved_scalars)
    _build_non_derivative_xml(
        root, table_i_rows, reference_year, doc_type, unresolved_scalars
    )
    _build_derivative_xml(
        root, table_ii_rows, reference_year, doc_type, unresolved_scalars
    )

    if footnotes:
        fn_container = ET.SubElement(root, "footnotes")
        for fn_id, fn_text in sorted(footnotes.items()):
            fn_el = ET.SubElement(fn_container, "footnote")
            fn_el.attrib["id"] = f"F{fn_id}"
            fn_el.text = fn_text

    if metadata.signature_name or metadata.signature_date:
        sig_el = ET.SubElement(root, "ownerSignature")
        _add_metadata_field(
            sig_el,
            "signatureName",
            metadata.signature_name,
            reference_year,
            unresolved_scalars,
        )
        _add_metadata_field(
            sig_el,
            "signatureDate",
            metadata.signature_date,
            reference_year,
            unresolved_scalars,
        )

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
