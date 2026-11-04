from __future__ import annotations

import pytest

from edgar_sec.engine.forms.form_c.renderer import render_form_c_to_xml
from tests.engine.forms.form_c.test_xml_parser import _OFFERING_XML


def test_native_document_passes_through_byte_identical() -> None:
    out = render_form_c_to_xml(_OFFERING_XML)
    assert out.content == _OFFERING_XML


def test_non_native_payload_is_refused() -> None:
    with pytest.raises(ValueError):
        render_form_c_to_xml(b"<notificationOfRemoval/>")
