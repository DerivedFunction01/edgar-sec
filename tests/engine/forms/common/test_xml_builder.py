"""Tests for the shared canonical XML builder."""

import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.xml_builder import (
    add_text_element,
    canonical_xml_output,
    child_element,
    root_element,
    serialize_canonical_xml,
)


def test_root_element_with_attrib() -> None:
    root = root_element("root", {"xmlns": "urn:example"})
    assert serialize_canonical_xml(root) == (
        b"<?xml version='1.0' encoding='utf-8'?>\n<root xmlns=\"urn:example\" />"
    )


def test_add_text_element_sets_text_and_keeps_empty() -> None:
    root = ET.Element("root")
    add_text_element(root, "filled", "value")
    add_text_element(root, "empty", None)
    assert serialize_canonical_xml(root) == (
        b"<?xml version='1.0' encoding='utf-8'?>\n"
        b"<root><filled>value</filled><empty /></root>"
    )


def test_child_element_appends_empty_child() -> None:
    root = ET.Element("root")
    child = child_element(root, "kid")
    add_text_element(child, "leaf", "x")
    assert root.find("kid/leaf") is not None


def test_canonical_xml_output_envelope() -> None:
    root = ET.Element("root")
    output = canonical_xml_output(root)
    assert output.content == (b"<?xml version='1.0' encoding='utf-8'?>\n<root />")
    assert len(output.sidecars) == 1
    assert output.sidecars[0].name == "unparsed_sections.json"
    assert output.sidecars[0].content == b'{"unparsed_sections":[]}'
