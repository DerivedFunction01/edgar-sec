"""Tests for Form 4 XML document generation."""

import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.ownership.render_to_xml import render_form4_to_xml

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
  <tr><td>Common Stock</td><td>06/01/2001</td><td>P</td><td>500 | A | $10.00</td><td>500</td><td>D</td><td></td></tr>
</table>
<table><tr><td>Signature of Reporting Person\nStephen V. Hooks\n07-03-2001</td></tr></table>
</body></html>
"""


def test_render_form4_to_xml_generates_valid_envelope() -> None:
    xml_bytes = render_form4_to_xml(SAMPLE_DOC_HTML)
    root = ET.fromstring(xml_bytes)

    assert root.tag == "ownershipDocument"
    assert root.findtext("schemaVersion") == "X0206"
    assert root.findtext("documentType") == "4"
    assert root.findtext("periodOfReport") == "June 2001"
    assert root.findtext("issuer/issuerName") == "ACME CORP"
    assert root.findtext("issuer/issuerTradingSymbol") == "ACM"
    assert (
        root.findtext("reportingOwner/reportingOwnerId/rptOwnerName")
        == "Hooks, Stephen V."
    )
    assert root.findtext("reportingOwner/reportingOwnerRelationship/isOfficer") == "1"

    tx = root.find("nonDerivativeTable/nonDerivativeTransaction")
    assert tx is not None
    assert tx.findtext("securityTitle/value") == "Common Stock"
    assert tx.findtext("transactionCoding/transactionCode") == "P"
    assert tx.findtext("transactionAmounts/transactionShares/value") == "500.0"

    assert root.findtext("ownerSignature/signatureName") == "Stephen V. Hooks"
    assert root.findtext("ownerSignature/signatureDate") == "07-03-2001"


def test_render_form4_to_xml_passthrough_for_xml_input() -> None:
    raw_xml = (
        b'<?xml version="1.0"?><ownershipDocument><test>true</test></ownershipDocument>'
    )
    result = render_form4_to_xml(raw_xml)
    assert result == raw_xml
