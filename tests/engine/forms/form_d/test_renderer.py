"""Tests for Form D XML renderer."""

from edgar_sec.engine.forms.form_d.renderer import render_form_d_to_xml
from edgar_sec.engine.forms.form_d.xml_parser import parse_form_d_xml
from edgar_sec.engine.forms.form_d.renderer import build_form_d_xml

_SAMPLE_XML = b"""<?xml version="1.0"?>
<edgarSubmission>
    <schemaVersion>X0707</schemaVersion>
    <submissionType>D</submissionType>
    <testOrLive>LIVE</testOrLive>
    <primaryIssuer>
        <cik>0001487198</cik>
        <entityName>ASPEN GROUP, INC.</entityName>
        <issuerAddress>
            <street1>1660 SOUTH ALBION STREET</street1>
            <city>DENVER</city>
            <stateOrCountry>CO</stateOrCountry>
            <zipCode>80222</zipCode>
        </issuerAddress>
    </primaryIssuer>
</edgarSubmission>"""


def test_render_form_d_passthrough() -> None:
    """Verify native XML passthrough returns identical content."""
    output = render_form_d_to_xml(_SAMPLE_XML)
    assert output.content == _SAMPLE_XML
    assert len(output.sidecars) == 1
    assert output.sidecars[0].name == "unparsed_sections.json"


def test_build_form_d_xml_from_model() -> None:
    """Verify building canonical XML from FormDDocument."""
    doc = parse_form_d_xml(_SAMPLE_XML)
    output = build_form_d_xml(doc)
    assert b"ASPEN GROUP, INC." in output.content
    assert b"<submissionType>D</submissionType>" in output.content
