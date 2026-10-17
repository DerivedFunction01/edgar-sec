"""Tests for Form 144 XML envelope rendering and pass-through."""

import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.form144.render_to_xml import render_form144_to_xml

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ownership">
  <headerData><submissionType>144</submissionType></headerData>
  <formData>
    <issuerInfo><issuerName>Acme Corp</issuerName></issuerInfo>
  </formData>
</edgarSubmission>
""".encode("utf-8")

SAMPLE_HTML = """
<html><body>
<table>
<tr><td>1 (a) NAME OF ISSUER</td><td>Beta Technologies Inc</td><td>(b) IRS IDENT. NO.</td><td>98-7654321</td></tr>
<tr><td>2 (a) NAME OF PERSON FOR WHOSE ACCOUNT SOLD</td><td>John Smith</td><td>(b) RELATIONSHIP TO ISSUER</td><td>Director</td></tr>
</table>
<table>
<tr><td>3 (a) Title of the Class</td><td>(b) Name of Broker</td><td>(c) Number of Shares To Be Sold</td></tr>
<tr><td>Common Stock</td><td>Goldman Sachs</td><td>10,000</td></tr>
</table>
<table>
<tr><td>TABLE I - SECURITIES TO BE SOLD</td></tr>
<tr><td>Common Stock</td><td>01/01/2021</td><td>Direct Purchase</td><td>Issuer</td><td>10,000</td></tr>
</table>
<table>
<tr><td>TABLE II - SECURITIES SOLD DURING THE PAST 3 MONTHS</td></tr>
<tr><td>None</td></tr>
</table>
<table><tr><td>REMARKS: Delivery under the equity compensation plan.</td></tr></table>
<table><tr><td>/s/ John Smith</td></tr></table>
</body></html>
""".encode("utf-8")


def test_native_xml_pass_through():
    xml_bytes = render_form144_to_xml(SAMPLE_XML)
    root = ET.fromstring(xml_bytes)
    assert "edgarSubmission" in root.tag
    submission_type = root.find(".//{*}submissionType")
    assert submission_type is not None and submission_type.text == "144"


def test_html_to_xml_conversion():
    xml_bytes = render_form144_to_xml(SAMPLE_HTML)
    root = ET.fromstring(xml_bytes)
    assert "edgarSubmission" in root.tag
    issuer = root.find(".//{*}issuerName")
    assert issuer is not None and issuer.text == "Beta Technologies Inc"
    seller = root.find(".//{*}nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold")
    assert seller is not None and seller.text == "John Smith"
    shares = root.find(".//{*}noOfUnitsSold")
    assert shares is not None and shares.text == "10000"
    nothing_to_report = root.find(
        ".//{*}nothingToReportFlagOnSecuritiesSoldInPast3Months"
    )
    assert nothing_to_report is not None and nothing_to_report.text == "Y"
    remarks = root.find(".//{*}remarks")
    assert (
        remarks is not None
        and remarks.text == "Delivery under the equity compensation plan."
    )
