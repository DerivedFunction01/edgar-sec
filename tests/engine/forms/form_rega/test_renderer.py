from __future__ import annotations

import pytest

from edgar_sec.engine.forms.form_rega.renderer import (
    render_rega_annual_to_xml,
    render_rega_exit_to_xml,
    render_rega_offering_to_xml,
)
from tests.engine.forms.form_rega.test_xml_parser import (
    _ANNUAL_XML,
    _EXIT_XML,
    _OFFERING_XML,
)


def test_native_documents_pass_through_byte_identical() -> None:
    assert render_rega_offering_to_xml(_OFFERING_XML).content == _OFFERING_XML
    assert render_rega_annual_to_xml(_ANNUAL_XML).content == _ANNUAL_XML
    assert render_rega_exit_to_xml(_EXIT_XML).content == _EXIT_XML


def test_cross_kind_payloads_are_refused() -> None:
    with pytest.raises(ValueError):
        render_rega_offering_to_xml(_ANNUAL_XML)
    with pytest.raises(ValueError):
        render_rega_annual_to_xml(_EXIT_XML)
    with pytest.raises(ValueError):
        render_rega_exit_to_xml(_OFFERING_XML)


def test_non_xml_payload_is_refused() -> None:
    with pytest.raises(ValueError):
        render_rega_offering_to_xml(b"<html><body>1-A</body></html>")
