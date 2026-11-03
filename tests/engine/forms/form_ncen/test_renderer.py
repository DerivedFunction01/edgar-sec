"""Tests for the Form N-CEN canonical XML renderer."""

from edgar_sec.domain.forms.families.form_ncen.models import FormNCenDocument
from edgar_sec.engine.document_processing.capabilities import has_capability
from edgar_sec.engine.document_processing.registry import DEFAULT_HANDLER_REGISTRY
from edgar_sec.engine.forms.form_ncen.renderer import (
    build_ncen_xml,
    render_ncen_to_xml,
)
from edgar_sec.engine.forms.form_ncen.xml_parser import parse_ncen_xml

_NATIVE = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ncen">
  <headerData><submissionType>N-CEN</submissionType></headerData>
</edgarSubmission>
"""


def test_render_native_passthrough() -> None:
    """Native spec XML passes through byte-identical."""
    output = render_ncen_to_xml(_NATIVE)
    assert output.content == _NATIVE


def test_build_round_trip() -> None:
    """A built document re-parses to the same typed values."""
    doc = FormNCenDocument(
        submission_type="N-CEN",
        registrant_name="ACME INCOME FUND",
        directors=("JANE DOE",),
        file_number="811-00000",
        registrant_cik="0000123456",
        classification_type="N-2",
    )
    output = build_ncen_xml(doc)
    reparsed = parse_ncen_xml(output.content)
    assert reparsed.registrant_name == "ACME INCOME FUND"
    assert reparsed.directors == ("JANE DOE",)
    assert reparsed.file_number == "811-00000"


def test_registry_and_capability() -> None:
    """The handler is registered for the N-CEN family."""
    assert has_capability("form_ncen_to_xml")
    registration = DEFAULT_HANDLER_REGISTRY.get("form_ncen_to_xml", "render_to_xml")
    assert registration is not None
    assert registration.family == "n-cen"
