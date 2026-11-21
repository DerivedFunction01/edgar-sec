"""Tests for the Form N-PORT canonical XML renderer."""

from edgar_sec.domain.forms.families.form_nport.models import (
    FormNPortDocument,
    NPortInvestment,
)
from edgar_sec.engine.document_processing.capabilities import has_capability
from edgar_sec.engine.document_processing.registry import DEFAULT_HANDLER_REGISTRY
from edgar_sec.engine.forms.form_nport.renderer import (
    build_nport_xml,
    render_nport_to_xml,
)
from edgar_sec.engine.forms.form_nport.xml_parser import parse_nport_xml

_NATIVE = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <headerData><submissionType>NPORT-P</submissionType></headerData>
</edgarSubmission>
"""


def test_render_native_passthrough() -> None:
    """Native spec XML passes through byte-identical."""
    output = render_nport_to_xml(_NATIVE)
    assert output.content == _NATIVE


def test_build_round_trip() -> None:
    """A built document re-parses to the same typed values."""
    doc = FormNPortDocument(
        submission_type="NPORT-P",
        registrant_name="ACME FUND TRUST",
        investments=(
            NPortInvestment(
                name="ACME CORP",
                title="ACME COMMON",
                cusip="001000000",
                isin="US0010000000",
                currency_code="USD",
                value_usd="500.00",
            ),
        ),
        series_name="ACME GROWTH FUND",
        net_assets="975.00",
    )
    output = build_nport_xml(doc)
    reparsed = parse_nport_xml(output.content)
    assert reparsed.registrant_name == "ACME FUND TRUST"
    assert reparsed.investments[0].isin == "US0010000000"
    assert reparsed.investments[0].currency_code == "USD"
    assert reparsed.net_assets == "975.00"


def test_registry_and_capability() -> None:
    """The handler is registered for the N-PORT family."""
    assert has_capability("form_nport_to_xml")
    registration = DEFAULT_HANDLER_REGISTRY.get("form_nport_to_xml", "render_to_xml")
    assert registration is not None
    assert registration.family == "n-port"
