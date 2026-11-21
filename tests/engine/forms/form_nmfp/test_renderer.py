"""Tests for the Form N-MFP canonical XML renderer."""

from edgar_sec.domain.forms.families.form_nmfp.models import (
    FormNMfpDocument,
    NMfpSecurity,
)
from edgar_sec.engine.document_processing.capabilities import has_capability
from edgar_sec.engine.document_processing.registry import DEFAULT_HANDLER_REGISTRY
from edgar_sec.engine.forms.form_nmfp.renderer import (
    build_nmfp_xml,
    render_nmfp_to_xml,
)
from edgar_sec.engine.forms.form_nmfp.xml_parser import parse_nmfp_xml

_NATIVE_GEN2 = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp2">
  <headerData><submissionType>N-MFP2</submissionType></headerData>
</edgarSubmission>
"""


def test_render_gen2_passthrough() -> None:
    """Older-generation XML passes through as filed, never converted."""
    output = render_nmfp_to_xml(_NATIVE_GEN2)
    assert output.content == _NATIVE_GEN2


def test_build_round_trip() -> None:
    """A built document re-parses to the same typed values."""
    doc = FormNMfpDocument(
        submission_type="N-MFP3",
        securities=(
            NMfpSecurity(
                issuer_name="US TREASURY",
                title="T-BILL",
                cusip="912797PU5",
                percent_of_net_assets="0.88",
            ),
        ),
        generation=3,
        series_name="ACME GOVERNMENT FUND",
        report_date="2025-06-30",
    )
    output = build_nmfp_xml(doc)
    reparsed = parse_nmfp_xml(output.content)
    assert reparsed.series_name == "ACME GOVERNMENT FUND"
    assert reparsed.securities[0].cusip == "912797PU5"


def test_registry_and_capability() -> None:
    """The handler is registered for the N-MFP family."""
    assert has_capability("form_nmfp_to_xml")
    registration = DEFAULT_HANDLER_REGISTRY.get("form_nmfp_to_xml", "render_to_xml")
    assert registration is not None
    assert registration.family == "n-mfp"
