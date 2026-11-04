from __future__ import annotations

import pytest

from edgar_sec.engine.forms.form_25nse.renderer import (
    build_form_25nse_xml,
    render_form_25nse_to_xml,
)
from edgar_sec.engine.forms.form_25nse.xml_parser import parse_form_25nse_xml
from tests.engine.forms.form_25nse.test_xml_parser import _BARE_XML, _WRAPPER_XML


def test_native_document_passes_through_byte_identical() -> None:
    out = render_form_25nse_to_xml(_BARE_XML)
    assert out.content == _BARE_XML


def test_wrapper_rebuilds_to_parseable_notification() -> None:
    out = render_form_25nse_to_xml(_WRAPPER_XML)
    doc = parse_form_25nse_xml(out.content)
    assert doc is not None
    assert doc.issuer.file_number == "001-00001"
    assert doc.rule_provision == "17 CFR 240.12d2-2(b)"


def test_build_round_trips_through_parser() -> None:
    doc = parse_form_25nse_xml(_BARE_XML)
    assert doc is not None
    rebuilt = build_form_25nse_xml(doc)
    again = parse_form_25nse_xml(rebuilt.content)
    assert again == doc


def test_unparseable_payload_raises() -> None:
    with pytest.raises(ValueError):
        render_form_25nse_to_xml(b"<html>not a notification</html>")
