"""Tests for Form 4 XML document generation."""

import xml.etree.ElementTree as ET
from types import SimpleNamespace

from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.ownership.render_to_xml import render_ownership_to_xml

SAMPLE_DOC_HTML = b"""
<html><body>
<table><tr>
  <td>1. Name and Address of Reporting Person* Hooks, Stephen V. (Last) (First) 3400 North Wolf Road Franklin Park, IL 60131</td>
  <td>2. Issuer Name and Ticker Symbol ACME CORP ACM</td>
  <td>4. Statement for June 2001</td>
  <td>6. Relationship Director X Officer Description VP</td>
</tr></table>
<table><tr><td>Table I - Non-Derivative Securities</td></tr></table>
<table>
  <tr><td>Title</td><td>Date</td><td>Code</td><td>Amount</td><td>Owned</td><td>Form</td><td>Nature</td></tr>
  <tr><td>Common Stock</td><td>06/01/2001</td><td>P</td><td>500.000 | A | $10.00</td><td>500.000</td><td>D</td><td></td></tr>
</table>
<table><tr><td>Signature of Reporting Person\nStephen V. Hooks\n07-03-2001</td></tr></table>
</body></html>
"""


def test_render_ownership_to_xml_generates_valid_envelope() -> None:
    result = render_ownership_to_xml(SAMPLE_DOC_HTML)
    xml_bytes = result.content if isinstance(result, HandlerOutput) else result
    root = ET.fromstring(xml_bytes)

    assert root.tag == "ownershipDocument"
    assert root.find("schemaVersion") is None
    assert root.findtext("documentType") == "4"
    assert root.findtext("periodOfReport") == "2001-06-01"
    assert root.find("issuer/issuerName") is None
    assert root.findtext("issuer/issuerTradingSymbol") == "ACM"
    assert root.find("reportingOwner/reportingOwnerId/rptOwnerName") is None
    assert root.findtext("reportingOwner/reportingOwnerRelationship/isOfficer") == "1"
    assert (
        root.findtext("reportingOwner/reportingOwnerAddress/rptOwnerNonUSAddressFlag")
        == "0"
    )

    tx = root.find("nonDerivativeTable/nonDerivativeTransaction")
    assert tx is not None
    assert tx.findtext("securityTitle/value") == "Common Stock"
    assert tx.findtext("transactionCoding/transactionCode") == "P"
    assert tx.findtext("transactionAmounts/transactionShares/value") == "500"
    assert tx.findtext("transactionAmounts/transactionPricePerShare/value") == "10.00"
    assert (
        tx.findtext("postTransactionAmounts/sharesOwnedFollowingTransaction/value")
        == "500"
    )

    assert root.findtext("ownerSignature/signatureName") == "Stephen V. Hooks"
    assert root.findtext("ownerSignature/signatureDate") == "2001-07-03"


def test_render_ownership_to_xml_passthrough_for_xml_input() -> None:
    raw_xml = (
        b'<?xml version="1.0"?><ownershipDocument><test>true</test></ownershipDocument>'
    )
    result = render_ownership_to_xml(raw_xml)
    assert result == raw_xml


def test_renderer_moves_unparsed_html_to_sidecar() -> None:
    source = SAMPLE_DOC_HTML.replace(
        b"<table><tr><td>Signature of Reporting Person",
        b"<table><tr><td>Additional unclassified section</td></tr></table>"
        b"<table><tr><td>Signature of Reporting Person",
    )

    result = render_ownership_to_xml(source)

    assert isinstance(result, HandlerOutput)
    root = ET.fromstring(result.content)
    assert root.find(".//unparsedSection") is None
    assert len(result.sidecars) == 1
    assert result.sidecars[0].name == "unparsed_sections.json"
    assert b'"content_type":"text/html"' in result.sidecars[0].content
    assert b"Additional unclassified section" in result.sidecars[0].content


def test_renderer_anchors_two_digit_dates_to_report_period() -> None:
    source = SAMPLE_DOC_HTML.replace(b"06/01/2001", b"06/01/01").replace(
        b"07-03-2001", b"07-03-01"
    )

    result = render_ownership_to_xml(source)

    assert isinstance(result, bytes)
    root = ET.fromstring(result)
    assert root.findtext("periodOfReport") == "2001-06-01"
    assert root.findtext("ownerSignature/signatureDate") == "2001-07-03"


def test_render_ownership_to_xml_ascii_input() -> None:
    ascii_bytes = (
        b"FORM 4\n"
        b"1. Name and Address of Reporting Person*\n"
        b"Smith, Jane\n"
        b"2. Issuer Name and Ticker or Trading Symbol\n"
        b"ACME CORP (ACM)\n"
        b"4. Statement for Month/Day/Year\n"
        b"06/01/2001\n"
        b"6. Relationship of Reporting Person\n"
        b"[X] Director\n"
        b"<TABLE>\n"
        b"<CAPTION>\n"
        b"Table I - Non-Derivative Securities\n"
        b"<S>              <C>          <C>    <C>      <C>      <C>    <C>\n"
        b"1. Title         2. Date      3.Code 4.Amount 5.Owned  6.Form 7.Nature\n"
        b"Common Stock     06/01/2001   P      200 A    200      D\n"
        b"</TABLE>\n"
        b"/s/ Jane Smith   06/01/2001\n"
    )
    xml_bytes = render_ownership_to_xml(ascii_bytes)
    root = ET.fromstring(xml_bytes)
    assert root.tag == "ownershipDocument"
    assert root.findtext("issuer/issuerTradingSymbol") == "ACM"
    assert root.findtext("reportingOwner/reportingOwnerRelationship/isDirector") == "1"
    tx = root.find("nonDerivativeTable/nonDerivativeTransaction")
    assert tx is not None
    assert tx.findtext("transactionCoding/transactionCode") == "P"


def test_form5_uses_form5_document_and_transaction_types() -> None:
    result = render_ownership_to_xml(SAMPLE_DOC_HTML, SimpleNamespace(family="5"))
    xml_bytes = result.content if isinstance(result, HandlerOutput) else result
    root = ET.fromstring(xml_bytes)

    assert root.findtext("documentType") == "5"
    assert (
        root.findtext(
            "nonDerivativeTable/nonDerivativeTransaction/transactionCoding/transactionFormType"
        )
        == "5"
    )


def test_form3_does_not_mislabel_form4_transaction_rows() -> None:
    result = render_ownership_to_xml(SAMPLE_DOC_HTML, SimpleNamespace(family="3"))
    assert isinstance(result, HandlerOutput)
    root = ET.fromstring(result.content)

    assert root.findtext("documentType") == "3"
    assert root.find("nonDerivativeTable/nonDerivativeTransaction") is None
    assert b"Common Stock" in result.sidecars[0].content


def test_form3_holding_table_uses_shared_row_extractor() -> None:
    source = SAMPLE_DOC_HTML.replace(
        b"<tr><td>Title</td><td>Date</td><td>Code</td><td>Amount</td><td>Owned</td><td>Form</td><td>Nature</td></tr>",
        b"<tr><td>Title</td><td>Date</td><td>Deemed</td><td>Code</td><td>Swap</td><td>Amount</td><td>A/D</td><td>Price</td><td>Owned</td><td>Form</td><td>Nature</td></tr>",
    ).replace(
        b"<tr><td>Common Stock</td><td>06/01/2001</td><td>P</td><td>500.000 | A | $10.00</td><td>500.000</td><td>D</td><td></td></tr>",
        b"<tr><td>Common Stock</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>500.000</td><td>D</td><td></td></tr>",
    )
    result = render_ownership_to_xml(source, SimpleNamespace(family="3"))
    xml_bytes = result.content if isinstance(result, HandlerOutput) else result
    root = ET.fromstring(xml_bytes)

    holding = root.find("nonDerivativeTable/nonDerivativeHolding")
    assert holding is not None
    assert (
        holding.findtext("postTransactionAmounts/sharesOwnedFollowingTransaction/value")
        == "500"
    )
    assert root.find("nonDerivativeTable/nonDerivativeTransaction") is None
    if isinstance(result, HandlerOutput):
        assert b"non_derivative_table" not in result.sidecars[0].content


def test_report_date_anchors_two_digit_transaction_dates() -> None:
    source = SAMPLE_DOC_HTML.replace(b"06/01/2001", b"06/01/40")

    result = render_ownership_to_xml(
        source,
        SimpleNamespace(family="4", report_date="2024-12-31", filing_date="2019-12-31"),
    )
    xml_bytes = result.content if isinstance(result, HandlerOutput) else result
    root = ET.fromstring(xml_bytes)

    assert (
        root.findtext(
            "nonDerivativeTable/nonDerivativeTransaction/transactionDate/value"
        )
        == "2040-06-01"
    )


def test_filing_date_anchors_two_digit_dates_without_a_report_date() -> None:
    source = SAMPLE_DOC_HTML.replace(b"06/01/2001", b"06/01/40")

    result = render_ownership_to_xml(
        source, SimpleNamespace(family="4", filing_date="2019-12-31")
    )
    xml_bytes = result.content if isinstance(result, HandlerOutput) else result
    root = ET.fromstring(xml_bytes)

    assert (
        root.findtext(
            "nonDerivativeTable/nonDerivativeTransaction/transactionDate/value"
        )
        == "1940-06-01"
    )


def test_unanchored_two_digit_dates_are_omitted_and_recorded() -> None:
    source = (
        SAMPLE_DOC_HTML.replace(b"June 2001", b"June 01")
        .replace(b"06/01/2001", b"06/01/01")
        .replace(b"07-03-2001", b"07-03-01")
    )

    result = render_ownership_to_xml(source, SimpleNamespace(family="4"))

    assert isinstance(result, HandlerOutput)
    root = ET.fromstring(result.content)
    assert root.findtext("periodOfReport") is None
    assert (
        root.find("nonDerivativeTable/nonDerivativeTransaction/transactionDate") is None
    )
    assert b"normalization.unresolved:periodOfReport" in result.sidecars[0].content
    assert b"normalization.unresolved:table_i[0].transactionDate" in (
        result.sidecars[0].content
    )


def test_invalid_numeric_values_are_omitted_and_recorded() -> None:
    source = SAMPLE_DOC_HTML.replace(
        b"<tr><td>Common Stock</td><td>06/01/2001</td><td>P</td><td>500.000 | A | $10.00</td><td>500.000</td><td>D</td><td></td></tr>",
        b"<tr><td>Common Stock</td><td>06/01/2001</td><td>P</td><td>-500 | A | $10.00</td><td>500.000</td><td>D</td><td></td></tr>",
    )

    result = render_ownership_to_xml(source, SimpleNamespace(family="4"))

    assert isinstance(result, HandlerOutput)
    root = ET.fromstring(result.content)
    assert (
        root.findtext(
            "nonDerivativeTable/nonDerivativeTransaction/transactionAmounts/transactionShares/value"
        )
        is None
    )
    assert b"normalization.unresolved:table_i[0].transactionShares" in (
        result.sidecars[0].content
    )


def test_unresolvable_dates_do_not_leave_empty_containers() -> None:
    source = (
        SAMPLE_DOC_HTML.replace(
            b"<tr><td>Common Stock</td><td>06/01/2001</td><td>P</td><td>500.000 | A | $10.00</td><td>500.000</td><td>D</td><td></td></tr>",
            b"<tr><td>Common Stock</td><td>06/01/01</td><td>P</td><td>500.000 | A | $10.00</td><td>500.000</td><td>D</td><td></td></tr>",
        )
        .replace(b"June 2001", b"June 01")
        .replace(b"07-03-2001", b"07-03-01")
    )

    result = render_ownership_to_xml(source, SimpleNamespace(family="4"))

    assert isinstance(result, HandlerOutput)
    root = ET.fromstring(result.content)
    transaction = root.find("nonDerivativeTable/nonDerivativeTransaction")
    assert transaction is not None
    for element in transaction.iter():
        assert len(element) or (element.text or "").strip(), element.tag


def test_full_year_source_date_anchors_two_digit_period() -> None:
    source = SAMPLE_DOC_HTML.replace(b"June 2001", b"June 01").replace(
        b"06/01/2001", b"06/01/01"
    )

    result = render_ownership_to_xml(source, SimpleNamespace(family="4"))

    xml_bytes = result.content if isinstance(result, HandlerOutput) else result
    root = ET.fromstring(xml_bytes)

    assert root.findtext("periodOfReport") == "2001-06-01"
    assert (
        root.findtext(
            "nonDerivativeTable/nonDerivativeTransaction/transactionDate/value"
        )
        == "2001-06-01"
    )
