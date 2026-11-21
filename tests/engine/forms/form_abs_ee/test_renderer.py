from __future__ import annotations

import pytest

from edgar_sec.engine.forms.form_abs_ee.renderer import render_abs_ee_to_xml
from tests.engine.forms.form_abs_ee.test_stream import _EX102, _EX103


def test_native_documents_pass_through_byte_identical() -> None:
    assert render_abs_ee_to_xml(_EX102).content == _EX102
    assert render_abs_ee_to_xml(_EX103).content == _EX103


def test_non_asset_payload_is_refused() -> None:
    with pytest.raises(ValueError):
        render_abs_ee_to_xml(b"<edgarSubmission/>")
