"""Tests for Form 4 XML document generation."""

import xml.etree.ElementTree as ET
from types import SimpleNamespace

from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.ownership.render_to_xml import render_ownership_to_xml
from edgar_sec.engine.forms.ownership.sections import partition_ownership_tables
from edgar_sec.engine.forms.ownership.table_ii import parse_table_ii_rows

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
    assert root.findtext("issuer/issuerName") == "ACME CORP"
    assert root.findtext("issuer/issuerTradingSymbol") == "ACM"
    assert (
        root.findtext("reportingOwner/reportingOwnerId/rptOwnerName")
        == "Hooks, Stephen V."
    )
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


def test_a_derivative_transaction_keeps_its_ownership_nature() -> None:
    html = b"""
<html><body>
<table><tr><td>Table II - Derivative Securities Acquired, Disposed of, or Beneficially Owned</td></tr></table>
<table>
  <tr><td>1. Title of Derivative Security</td><td>2. Conversion or Exercise Price</td>
      <td>3. Transaction Date</td><td>4. Code</td><td>5. Amount</td>
      <td>6. Date Exercisable and Exp Date</td><td>7. Title and Amount Underlying</td>
      <td>8. Price</td><td>9. Following</td><td>10. Form</td><td>11. Nature</td></tr>
  <tr><td>Deferred Compensation Units</td><td>$0.0000</td><td>05/09/2002</td><td>A</td>
      <td>117.8600</td><td></td><td>Common Stock</td><td></td><td></td><td>I</td>
      <td>Deferred Compensation Stock Program</td></tr>
</table>
</body></html>
"""
    result = render_ownership_to_xml(html)
    xml_bytes = result.content if isinstance(result, HandlerOutput) else result
    root = ET.fromstring(xml_bytes)

    nature = root.find("derivativeTable/derivativeTransaction/ownershipNature")
    assert nature is not None
    assert nature.findtext("directOrIndirectOwnership/value") == "I"
    assert (
        nature.findtext("natureOfOwnership/value")
        == "Deferred Compensation Stock Program"
    )


def test_accession_0000950103_02_001311_preserves_positioned_amounts() -> None:
    html = b"""
<html><body>
<table><tr><td>Table II - Derivative Securities Acquired, Disposed of, or Beneficially Owned</td></tr></table>
<table>
  <tr>
    <td rowspan="2">1. Title of Derivative Security</td>
    <td rowspan="2">2. Conversion or Exercise Price</td>
    <td rowspan="2">3. Transaction Date</td>
    <td rowspan="2">3A. Deemed Execution Date</td>
    <td colspan="2">4. Transaction Code</td>
    <td colspan="2">5. Derivative Securities Acquired or Disposed</td>
    <td colspan="2">6. Date Exercisable and Expiration</td>
    <td colspan="2">7. Title and Amount of Underlying Securities</td>
    <td rowspan="2">8. Price</td><td rowspan="2">9. Following</td>
    <td rowspan="2">10. Form</td><td rowspan="2">11. Nature</td>
  </tr>
  <tr>
    <td>Code</td><td>V</td><td>Acquired (A)</td><td>Disposed (D)</td>
    <td>Date Exercisable</td><td>Expiration Date</td><td>Title</td><td>Amount</td>
  </tr>
  <tr>
    <td>Option to Purchase Class A Special Common Stock</td><td>$32.8437</td>
    <td>11/18/02</td><td></td><td>A</td><td></td><td>13, 875</td><td></td>
    <td>Immediately</td><td>5/03/2009</td>
    <td>Class A Special Common Stock</td><td>13, 875</td><td></td>
    <td>13, 875</td><td>I</td><td>By GRAT</td>
  </tr>
</table>
</body></html>
"""
    sections = partition_ownership_tables(html.decode())
    rows = parse_table_ii_rows(sections.table_ii, reference_year=2002)

    assert len(rows) == 1
    row = rows[0]
    assert row.transaction_date == "2002-11-18"
    assert row.shares_amount == "13875"
    assert row.underlying_shares_amount == "13875"
    assert row.derivative_shares_owned_following == "13875"
    assert row.exercisable_date == "Immediately"

    result = render_ownership_to_xml(
        html,
        SimpleNamespace(family="4", report_date="2002-11-18", filing_date="2002-12-02"),
    )

    assert isinstance(result, HandlerOutput)
    root = ET.fromstring(result.content)
    transaction = root.find("derivativeTable/derivativeTransaction")
    assert transaction is not None
    assert transaction.findtext("transactionAmounts/transactionShares/value") == "13875"
    assert (
        transaction.findtext("transactionAmounts/transactionAcquiredDisposedCode/value")
        == "A"
    )
    assert (
        transaction.findtext("underlyingSecurity/underlyingSecurityShares/value")
        == "13875"
    )
    assert (
        transaction.findtext(
            "postTransactionAmounts/sharesOwnedFollowingTransaction/value"
        )
        == "13875"
    )
    dates = transaction.find("exerciseDateAndExpirationDate")
    assert dates is not None
    assert dates.find("exerciseDate") is None
    assert dates.findtext("expirationDate/value") == "2009-05-03"
    assert transaction.findtext("transactionDate/value") == "2002-11-18"
    assert b'"normalization.unresolved:table_ii[0].exerciseDate"' in (
        result.sidecars[0].content
    )
    assert b'"content":"Immediately"' in result.sidecars[0].content
    for field in (
        "transactionShares",
        "underlyingSecurityShares",
        "sharesOwnedFollowingTransaction",
    ):
        assert f"normalization.unresolved:table_ii[0].{field}".encode() not in (
            result.sidecars[0].content
        )


def test_underlying_title_without_an_amount_is_retained_as_evidence() -> None:
    html = b"""
<html><body>
<table><tr><td>Table II - Derivative Securities Acquired</td></tr></table>
<table>
  <tr>
    <td>Title</td><td>Exercise Price</td><td>Transaction Date</td><td>Deemed Date</td>
    <td>Code</td><td>V</td><td>Acquired</td><td>Disposed</td>
    <td>Exercise Date</td><td>Expiration</td><td>Underlying Title</td>
    <td>Underlying Shares</td><td>Derivative Price</td><td>Following</td>
    <td>D/I</td><td>Nature</td>
  </tr>
  <tr>
    <td>Employee Stock Option</td><td>$10.00</td><td>06/01/2001</td><td></td>
    <td>A</td><td></td><td>100</td><td></td><td>06/01/2002</td><td>06/01/2011</td>
    <td>Common Stock</td><td></td><td></td><td>100</td><td>D</td><td></td>
  </tr>
</table>
</body></html>
"""
    result = render_ownership_to_xml(
        html,
        SimpleNamespace(family="4", report_date="2001-06-01", filing_date="2001-06-02"),
    )

    assert isinstance(result, HandlerOutput)
    transaction = ET.fromstring(result.content).find(
        "derivativeTable/derivativeTransaction"
    )
    assert transaction is not None
    assert transaction.find("underlyingSecurity") is None
    assert b'"normalization.unresolved:table_ii[0].underlyingSecurityTitle"' in (
        result.sidecars[0].content
    )
    assert b'"content":"Common Stock"' in result.sidecars[0].content
