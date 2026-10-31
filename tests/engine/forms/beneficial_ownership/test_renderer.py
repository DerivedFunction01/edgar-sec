"""Tests for beneficial ownership XML renderer."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.beneficial_ownership.renderer import (
    render_schedule13d_to_xml,
    render_schedule13g_to_xml,
)
from edgar_sec.engine.document_processing.outputs import HandlerOutput

_SAMPLE_HTML = b"""<html>
<body>
<p>SCHEDULE 13D</p>
<p>Alpha Issuer Inc.</p>
<p>(Name of Issuer)</p>
<p>000000000</p>
<p>(CUSIP Number)</p>
<p>1. NAMES OF REPORTING PERSONS</p>
<p>Beta Holdings LLC</p>
<p>2. CHECK THE APPROPRIATE BOX IF A MEMBER OF A GROUP</p>
<p>(a) [ ] (b) [X]</p>
<p>3. SEC USE ONLY</p>
<p>4. SOURCE OF FUNDS</p>
<p>WC</p>
<p>5. CHECK BOX IF DISCLOSURE OF LEGAL PROCEEDINGS</p>
<p style="font: 10pt Wingdings">o</p>
<p>6. CITIZENSHIP OR PLACE OF ORGANIZATION</p>
<p>Delaware</p>
<p>7. SOLE VOTING POWER</p>
<p>50,000</p>
<p>8. SHARED VOTING POWER</p>
<p>0</p>
<p>9. SOLE DISPOSITIVE POWER</p>
<p>50,000</p>
<p>10. SHARED DISPOSITIVE POWER</p>
<p>0</p>
<p>11. AGGREGATE AMOUNT BENEFICIALLY OWNED</p>
<p>50,000</p>
<p>12. CHECK BOX IF AGGREGATE AMOUNT EXCLUDES CERTAIN SHARES</p>
<p style="font: 10pt Wingdings">o</p>
<p>13. PERCENT OF CLASS</p>
<p>5.0%</p>
<p>14. TYPE OF REPORTING PERSON</p>
<p>OO</p>
<p>Item 1. Security and Issuer.</p>
<p>Relates to Common Stock.</p>
<p>SIGNATURE</p>
<p>Dated: January 1, 2020</p>
<p>By: /s/ Jane Smith</p>
<p>Name: Jane Smith</p>
<p>Title: Manager</p>
</body>
</html>
"""


def test_render_schedule13d_to_xml_generates_valid_xml() -> None:
    output = render_schedule13d_to_xml(_SAMPLE_HTML)
    assert isinstance(output, HandlerOutput)
    xml_bytes = output.content
    assert isinstance(xml_bytes, bytes)
    root = ET.fromstring(xml_bytes)
    assert "edgarSubmission" in root.tag
    schema_ver = root.find("{http://www.sec.gov/edgar/schedule13D}schemaVersion")
    assert schema_ver is not None and schema_ver.text == "X0202"

    person = root.find(".//{http://www.sec.gov/edgar/schedule13D}reportingPersonName")
    assert person is not None and person.text == "Beta Holdings LLC"

    legal = root.find(".//{http://www.sec.gov/edgar/schedule13D}legalProceedings")
    assert legal is not None and legal.text == "N"

    shares = root.find(".//{http://www.sec.gov/edgar/schedule13D}soleVotingPower")
    assert shares is not None and shares.text == "50000"

    signature = root.find(".//{http://www.sec.gov/edgar/schedule13D}signature")
    assert signature is not None and signature.text == "Jane Smith"
    signature_date = root.find(".//{http://www.sec.gov/edgar/schedule13D}date")
    assert signature_date is not None and signature_date.text == "01-01-2020"
    item_text = root.find(
        ".//{http://www.sec.gov/edgar/schedule13D}item1/"
        "{http://www.sec.gov/edgar/schedule13D}commentText"
    )
    assert item_text is not None and "Jane Smith" not in (item_text.text or "")

    assert (
        root.find(".//{http://www.sec.gov/edgar/schedule13D}extractionProvenance")
        is None
    )
    assert (
        root.find(".//{http://www.sec.gov/edgar/schedule13D}unparsedSections") is None
    )
    assert len(output.sidecars) == 1
    assert output.sidecars[0].name == "unparsed_sections.json"
    payload = json.loads(output.sidecars[0].content)
    assert set(payload) == {"unparsed_sections"}


def test_render_schedule13d_to_xml_passes_through_native_xml() -> None:
    native = b"""<?xml version="1.0" encoding="utf-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D" xmlns:com="http://www.sec.gov/edgar/common">
<schemaVersion>X0202</schemaVersion>
</edgarSubmission>"""
    output = render_schedule13d_to_xml(native)
    assert isinstance(output, HandlerOutput)
    assert output.content == native


def test_render_schedule13g_to_xml_passes_through_native_xml() -> None:
    native = b"""<?xml version="1.0" encoding="utf-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13G" xmlns:com="http://www.sec.gov/edgar/common">
<schemaVersion>X0202</schemaVersion>
</edgarSubmission>"""
    output = render_schedule13g_to_xml(native)
    assert isinstance(output, HandlerOutput)
    assert output.content == native


def test_render_schedule13g_to_xml_passes_through_lowercase_native_xml() -> None:
    native = b"""<?xml version="1.0" encoding="utf-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g" xmlns:com="http://www.sec.gov/edgar/common">
<headerData><submissionType>SCHEDULE 13G</submissionType></headerData>
</edgarSubmission>"""
    output = render_schedule13g_to_xml(native)
    assert isinstance(output, HandlerOutput)
    assert output.content == native


def test_unresolved_scalars_are_sidecar_evidence_not_xml_values() -> None:
    html = _SAMPLE_HTML.replace(b"50,000</p>", b"12 shares and more</p>", 1)
    output = render_schedule13d_to_xml(html)
    assert isinstance(output.content, bytes)
    root = ET.fromstring(output.content)
    assert root.find(".//{http://www.sec.gov/edgar/schedule13D}soleVotingPower") is None
    payload = json.loads(output.sidecars[0].content)
    unresolved = [
        item
        for item in payload["unparsed_sections"]
        if str(item["role"]).startswith("normalization.unresolved:")
    ]
    assert unresolved
