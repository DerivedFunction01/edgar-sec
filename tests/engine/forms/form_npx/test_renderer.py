"""Tests for the Form N-PX canonical XML renderer."""

from edgar_sec.domain.forms.families.form_npx.models import (
    FormNPxDocument,
    ProxyVoteRow,
)
from edgar_sec.engine.document_processing.capabilities import has_capability
from edgar_sec.engine.document_processing.registry import DEFAULT_HANDLER_REGISTRY
from edgar_sec.engine.forms.form_npx.renderer import (
    build_npx_xml,
    render_npx_to_xml,
)
from edgar_sec.engine.forms.form_npx.xml_parser import parse_npx_xml

_NATIVE = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/npx">
  <headerData><submissionType>N-PX</submissionType></headerData>
</edgarSubmission>
"""

_TEXT_ERA = b"""FORM N-PX
Investment Company Act file number: 811-41
General American Investors Company, Inc.
(Exact name of registrant as specified in charter)
Date of reporting period:  July 1, 2003 - June 30, 2004
"""


def test_render_native_passthrough() -> None:
    """Native spec XML passes through byte-identical."""
    output = render_npx_to_xml(_NATIVE)
    assert output.content == _NATIVE


def test_render_text_era_converts() -> None:
    """A text-era filing converts into the current canonical model."""
    output = render_npx_to_xml(_TEXT_ERA)
    doc = parse_npx_xml(output.content)
    assert doc.file_number == "811-41"
    assert doc.period_of_report == "06/30/2004"
    assert doc.reporting_person_name == "General American Investors Company, Inc."


def test_build_vote_table_document() -> None:
    """A coverless document builds the standalone vote table root."""
    doc = FormNPxDocument(
        submission_type="",
        vote_rows=(
            ProxyVoteRow(
                issuer_name="ACME CORP",
                meeting_date="06/12/2025",
                vote_description="Election of directors",
                cusip="001000000",
                how_voted=("For",),
            ),
        ),
    )
    output = build_npx_xml(doc)
    reparsed = parse_npx_xml(output.content)
    assert len(reparsed.vote_rows) == 1
    assert reparsed.vote_rows[0].how_voted == ("For",)


def test_registry_and_capability() -> None:
    """The handler is registered for the N-PX family."""
    assert has_capability("form_npx_to_xml")
    registration = DEFAULT_HANDLER_REGISTRY.get("form_npx_to_xml", "render_to_xml")
    assert registration is not None
    assert registration.family == "n-px"
