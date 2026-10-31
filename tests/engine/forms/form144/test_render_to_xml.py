"""Tests for Form 144 XML envelope rendering and pass-through."""

import xml.etree.ElementTree as ET

from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.form144.render_to_xml import render_form144_to_xml
from edgar_sec.engine.forms.common.unparsed import deserialize_unparsed_sections
from edgar_sec.engine.forms.common.extraction import normalize_value
from edgar_sec.engine.forms.form144.render_to_xml import (
    _xml_date,
)
from edgar_sec.engine.forms.form144.row_specs import (
    FORM144_TABLE_I_ROW_SPEC,
    FORM144_TABLE_II_ROW_SPEC,
)

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
    assert xml_bytes == SAMPLE_XML


def test_schema_scalar_normalization_uses_filing_year_anchor():
    assert _xml_date("01/15/09", 2023) == "01-15-2009"
    assert _xml_date("01/15/09", None) is None
    assert _xml_date("Jan 15, 09", 2023) == "01-15-2009"
    assert _xml_date("Jan 15, 09", None) is None


def test_numeric_columns_normalize_through_the_shared_row_specs():
    acquired = FORM144_TABLE_I_ROW_SPEC.column("amount_acquired")
    proceeds = FORM144_TABLE_II_ROW_SPEC.column("gross_proceeds")
    assert acquired is not None and proceeds is not None
    assert normalize_value("10,000", acquired.field) == "10000"
    assert normalize_value("10000.0", acquired.field) == "10000"
    assert normalize_value("$1,234.1200", proceeds.field) == "1234.1200"
    assert normalize_value("not-a-number", acquired.field) is None


def test_html_to_xml_conversion():
    result = render_form144_to_xml(SAMPLE_HTML)
    xml_bytes = result.content if isinstance(result, HandlerOutput) else result
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


def test_unparsed_tables_are_sidecars_not_schema_xml():
    html = b"<html><body><table><tr><td>Unclassified table content</td></tr></table></body></html>"
    result = render_form144_to_xml(html)
    assert isinstance(result, HandlerOutput)
    root = ET.fromstring(result.content)
    assert not any(elem.tag.endswith("unparsedSection") for elem in root.iter())
    assert len(result.sidecars) == 1
    assert result.sidecars[0].name == "unparsed_sections.json"
    records = deserialize_unparsed_sections(result.sidecars[0].content)
    assert records[0]["content_type"] == "text/html"
    assert "Unclassified table content" in records[0]["content"]
    assert "table_index" in records[0]


def test_invalid_numeric_values_are_omitted_and_recorded():
    html = SAMPLE_HTML.replace(
        b"<tr><td>Common Stock</td><td>01/01/2021</td><td>Direct Purchase</td><td>Issuer</td><td>10,000</td></tr>",
        b"<tr><td>Common Stock</td><td>01/01/2021</td><td>Direct Purchase</td><td>Issuer</td><td>-10,000</td></tr>",
    )

    result = render_form144_to_xml(html)

    assert isinstance(result, HandlerOutput)
    root = ET.fromstring(result.content)
    assert root.find(".//{*}amountOfSecuritiesAcquired") is None
    records = deserialize_unparsed_sections(result.sidecars[0].content)
    unresolved = [
        record for record in records if str(record["role"]).startswith("normalization.")
    ]
    assert unresolved
    assert unresolved[0]["content"] == "-10,000"
    assert unresolved[0]["normalization_status"]
