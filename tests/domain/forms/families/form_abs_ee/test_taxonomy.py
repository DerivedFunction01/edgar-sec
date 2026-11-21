from __future__ import annotations

from edgar_sec.domain.forms.families.form_abs_ee.taxonomy import (
    ASSETDATA_NAMESPACE_PREFIX,
    EXHIBIT_TYPES,
    HOST_FORMS,
    SPEC_ASSET_CLASSES,
)


def test_namespace_prefix_matches_abs_xml_spec() -> None:
    assert ASSETDATA_NAMESPACE_PREFIX == "http://www.sec.gov/edgar/document/absee/"
    assert "autolease" in SPEC_ASSET_CLASSES
    assert "rmbs" in SPEC_ASSET_CLASSES


def test_companion_scope() -> None:
    assert EXHIBIT_TYPES == ("EX-102", "EX-103")
    assert HOST_FORMS == ("ABS-EE", "10-D")
