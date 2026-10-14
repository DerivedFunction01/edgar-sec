"""Unit tests for safe streaming XML parser and QName extraction."""

import io
from edgar_sec.engine.xbrl.xml_parser import (
    resolve_href_qname,
    safe_iterparse,
    safe_parse_root,
    split_qname,
    strip_namespace,
)


def test_qname_splitting_and_namespace_stripping() -> None:
    """Verify Clark-notation and plain tag splitting."""
    ns, local = split_qname("{http://fasb.org/us-gaap/2024}Revenues")
    assert ns == "http://fasb.org/us-gaap/2024"
    assert local == "Revenues"
    assert strip_namespace("{http://www.xbrl.org/2003/linkbase}loc") == "loc"
    assert strip_namespace("plainTag") == "plainTag"


def test_resolve_href_qname() -> None:
    """Verify resolution of XLink href targets into standard QNames."""
    href1 = (
        "https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-2024.xsd#us-gaap_GrossProfit"
    )
    assert resolve_href_qname(href1) == "us-gaap:GrossProfit"
    href2 = "msft-20240630.xsd#msft_ServerProductsAndCloudServicesMember"
    assert resolve_href_qname(href2) == "msft:ServerProductsAndCloudServicesMember"
    assert resolve_href_qname("some_file.xsd#simple") == "simple"


def test_safe_iterparse_memory_bounded() -> None:
    """Verify safe_iterparse iterates and clears elements."""
    xml_data = b"<root><item id='1'/><item id='2'/><other/></root>"
    items = list(safe_iterparse(io.BytesIO(xml_data), tag="item"))
    assert len(items) == 2
    assert items[0][1].attrib["id"] == "1"
    assert items[1][1].attrib["id"] == "2"


def test_safe_parse_root() -> None:
    """Verify in-memory XML string and bytes parsing."""
    root = safe_parse_root(b"<root><child name='test'/></root>")
    assert root.tag == "root"
    assert root[0].attrib["name"] == "test"
