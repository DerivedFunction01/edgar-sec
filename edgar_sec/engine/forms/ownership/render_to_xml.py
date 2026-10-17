"""XML envelope generation for SEC Form 4 ownership documents."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.ownership.securities import (
    DerivativeTransaction,
    NonDerivativeTransaction,
    parse_footnotes,
    parse_table_i_rows,
    parse_table_ii_rows,
)
from edgar_sec.domain.forms.families.ownership.models import Form4Metadata
from edgar_sec.engine.document.html.cleaner import (
    strip_decorative_presentation_attributes,
)
from edgar_sec.engine.forms.ownership.metadata_parser import parse_metadata
from edgar_sec.engine.forms.ownership.sections import (
    OwnershipSections,
    partition_ownership_tables,
)

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext


def _add_text_elem(parent: ET.Element, tag: str, text: str | None) -> ET.Element:
    elem = ET.SubElement(parent, tag)
    if text is not None:
        elem.text = text
    return elem


def _add_valued_elem(
    parent: ET.Element, tag: str, value: str | float | None
) -> ET.Element:
    elem = ET.SubElement(parent, tag)
    val_elem = ET.SubElement(elem, "value")
    if value is not None:
        val_elem.text = str(value)
    return elem


def _build_issuer_xml(root: ET.Element, metadata: Form4Metadata) -> None:
    issuer_el = ET.SubElement(root, "issuer")
    _add_text_elem(issuer_el, "issuerName", metadata.issuer.name)
    _add_text_elem(issuer_el, "issuerTradingSymbol", metadata.issuer.trading_symbol)
    if metadata.issuer.irs_number:
        _add_text_elem(issuer_el, "issuerIrsNumber", metadata.issuer.irs_number)


def _build_owner_xml(root: ET.Element, metadata: Form4Metadata) -> None:
    owner_el = ET.SubElement(root, "reportingOwner")
    id_el = ET.SubElement(owner_el, "reportingOwnerId")
    _add_text_elem(id_el, "rptOwnerName", metadata.reporting_owner.name)

    addr_el = ET.SubElement(owner_el, "reportingOwnerAddress")
    _add_text_elem(addr_el, "rptOwnerStreet1", metadata.reporting_owner.street)
    _add_text_elem(addr_el, "rptOwnerCity", metadata.reporting_owner.city)
    _add_text_elem(addr_el, "rptOwnerState", metadata.reporting_owner.state)
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
    root: ET.Element, rows: list[NonDerivativeTransaction]
) -> None:
    table_el = ET.SubElement(root, "nonDerivativeTable")
    for r in rows:
        tx_el = ET.SubElement(
            table_el,
            (
                "nonDerivativeTransaction"
                if r.transaction_code or r.shares_amount
                else "nonDerivativeHolding"
            ),
        )
        _add_valued_elem(tx_el, "securityTitle", r.security_title)
        if r.transaction_date:
            _add_valued_elem(tx_el, "transactionDate", r.transaction_date)
        if r.transaction_code:
            coding_el = ET.SubElement(tx_el, "transactionCoding")
            _add_text_elem(coding_el, "transactionFormType", "4")
            _add_text_elem(coding_el, "transactionCode", r.transaction_code)
            _add_text_elem(
                coding_el,
                "equitySwapInvolved",
                "1" if r.equity_swap_involved else "0",
            )
        if (
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
        if r.shares_owned_following is not None:
            post_el = ET.SubElement(tx_el, "postTransactionAmounts")
            _add_valued_elem(
                post_el, "sharesOwnedFollowingTransaction", r.shares_owned_following
            )
        if r.direct_or_indirect:
            own_el = ET.SubElement(tx_el, "ownershipNature")
            _add_valued_elem(own_el, "directOrIndirectOwnership", r.direct_or_indirect)
            if r.nature_of_ownership:
                _add_valued_elem(own_el, "natureOfOwnership", r.nature_of_ownership)


def _build_derivative_xml(root: ET.Element, rows: list[DerivativeTransaction]) -> None:
    table_el = ET.SubElement(root, "derivativeTable")
    for r in rows:
        tx_el = ET.SubElement(
            table_el,
            (
                "derivativeTransaction"
                if r.transaction_code or r.shares_amount
                else "derivativeHolding"
            ),
        )
        _add_valued_elem(tx_el, "securityTitle", r.security_title)
        if r.conversion_or_exercise_price is not None:
            _add_valued_elem(
                tx_el,
                "conversionOrExercisePrice",
                r.conversion_or_exercise_price,
            )
        if r.transaction_date:
            _add_valued_elem(tx_el, "transactionDate", r.transaction_date)
        if r.transaction_code:
            coding_el = ET.SubElement(tx_el, "transactionCoding")
            _add_text_elem(coding_el, "transactionFormType", "4")
            _add_text_elem(coding_el, "transactionCode", r.transaction_code)
            _add_text_elem(
                coding_el,
                "equitySwapInvolved",
                "1" if r.equity_swap_involved else "0",
            )
        if r.exercisable_date or r.expiration_date:
            exp_el = ET.SubElement(tx_el, "exerciseDateAndExpirationDate")
            if r.exercisable_date:
                _add_valued_elem(exp_el, "exerciseDate", r.exercisable_date)
            if r.expiration_date:
                _add_valued_elem(exp_el, "expirationDate", r.expiration_date)
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
        if r.derivative_shares_owned_following is not None:
            post_el = ET.SubElement(tx_el, "postTransactionAmounts")
            _add_valued_elem(
                post_el,
                "sharesOwnedFollowingTransaction",
                r.derivative_shares_owned_following,
            )
        if r.direct_or_indirect:
            own_el = ET.SubElement(tx_el, "ownershipNature")
            _add_valued_elem(own_el, "directOrIndirectOwnership", r.direct_or_indirect)


def _build_unparsed_sections_xml(root: ET.Element, sections: OwnershipSections) -> None:
    unparsed_nodes = list(sections.unparsed)
    if not unparsed_nodes:
        return
    container = ET.SubElement(root, "unparsedSections")
    for sec in unparsed_nodes:
        unparsed_el = ET.SubElement(container, "unparsedSection")
        unparsed_el.attrib["tableIndex"] = str(sec.table_index)
        unparsed_el.attrib["role"] = str(sec.role)
        raw_html = getattr(sec.raw_node, "html", None)
        raw_str = raw_html() if callable(raw_html) else str(raw_html or "")
        unparsed_el.text = strip_decorative_presentation_attributes(raw_str)


def render_form4_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> bytes:
    """Transform historical Form 4 HTML into canonical SEC ownership XML."""
    stripped = raw_bytes.strip()
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<ownershipDocument"):
        return raw_bytes

    text = raw_bytes.decode("utf-8", errors="replace")
    sections = partition_ownership_tables(text)

    metadata = parse_metadata(sections.boxes_1_to_7, sections.signatures)
    table_i_rows = parse_table_i_rows(sections.table_i)
    table_ii_rows = parse_table_ii_rows(sections.table_ii)
    footnotes = parse_footnotes(sections.footnotes)

    root = ET.Element("ownershipDocument")
    _add_text_elem(root, "schemaVersion", "X0206")
    doc_type = context.family if context and context.family else "4"
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
    _add_text_elem(root, "periodOfReport", period)

    _build_issuer_xml(root, metadata)
    _build_owner_xml(root, metadata)
    _build_non_derivative_xml(root, table_i_rows)
    _build_derivative_xml(root, table_ii_rows)

    if footnotes:
        fn_container = ET.SubElement(root, "footnotes")
        for fn_id, fn_text in sorted(footnotes.items()):
            fn_el = ET.SubElement(fn_container, "footnote")
            fn_el.attrib["id"] = f"F{fn_id}"
            fn_el.text = fn_text

    if metadata.signature_name or metadata.signature_date:
        sig_el = ET.SubElement(root, "ownerSignature")
        _add_text_elem(sig_el, "signatureName", metadata.signature_name)
        _add_text_elem(sig_el, "signatureDate", metadata.signature_date)

    _build_unparsed_sections_xml(root, sections)

    ET.indent(root, space="    ")
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes


__all__ = [
    "render_form4_to_xml",
]
