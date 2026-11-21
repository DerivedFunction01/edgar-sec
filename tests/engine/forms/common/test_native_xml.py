"""Tests for streaming native SEC XML detection and passthrough."""

from __future__ import annotations

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec
from edgar_sec.engine.forms.common.native_xml import (
    inspect_sec_xml_root,
    is_native_sec_xml,
    passthrough_sec_xml,
)

_SAMPLE_SPEC = SecXmlSchemaSpec(
    namespaces=frozenset({"http://www.sec.gov/edgar/ownership"}),
    root_tags=frozenset({"ownershipDocument"}),
)


def test_inspect_sec_xml_root_extracts_namespace_and_tag() -> None:
    xml = b'<ownershipDocument xmlns="http://www.sec.gov/edgar/ownership"><item/></ownershipDocument>'
    assert inspect_sec_xml_root(xml) == (
        "http://www.sec.gov/edgar/ownership",
        "ownershipDocument",
    )


def test_inspect_sec_xml_root_returns_none_for_non_xml() -> None:
    assert inspect_sec_xml_root(b"<html><body>prose</body></html>") == (
        "",
        "html",
    )
    assert inspect_sec_xml_root(b"Just plain text") is None
    assert inspect_sec_xml_root(b"<?xml broken") is None


def test_is_native_sec_xml_validates_spec() -> None:
    valid = b'<ownershipDocument xmlns="http://www.sec.gov/edgar/ownership"><item/></ownershipDocument>'
    wrong_ns = (
        b'<ownershipDocument xmlns="http://example.com"><item/></ownershipDocument>'
    )
    wrong_tag = (
        b'<otherTag xmlns="http://www.sec.gov/edgar/ownership"><item/></otherTag>'
    )
    assert is_native_sec_xml(valid, _SAMPLE_SPEC)
    assert not is_native_sec_xml(wrong_ns, _SAMPLE_SPEC)
    assert not is_native_sec_xml(wrong_tag, _SAMPLE_SPEC)


def test_passthrough_sec_xml_produces_handler_output() -> None:
    valid = b'<ownershipDocument xmlns="http://www.sec.gov/edgar/ownership"/>'
    output = passthrough_sec_xml(valid, _SAMPLE_SPEC)
    assert output is not None
    assert output.content == valid
    assert len(output.sidecars) == 1
    assert output.sidecars[0].name == "unparsed_sections.json"
