"""Qname parse seam and declared prefix vocabulary."""

from edgar_sec.engine.xbrl.schema.models import (
    CORE_PREFIXES,
    STANDARD_PREFIXES,
    DefinitionArc,
    LinkbaseBundle,
    qname_local,
    split_concept_qname,
)


def test_split_concept_qname_qualified():
    assert split_concept_qname("us-gaap:Revenues") == ("us-gaap", "Revenues")


def test_split_concept_qname_unqualified():
    assert split_concept_qname("Revenues") == ("", "Revenues")


def test_split_concept_qname_extension_prefix():
    assert split_concept_qname("acme:CustomRevenue2024") == (
        "acme",
        "CustomRevenue2024",
    )


def test_qname_local():
    assert qname_local("us-gaap:Revenues") == "Revenues"
    assert qname_local("Revenues") == "Revenues"


def test_prefix_vocabulary():
    assert CORE_PREFIXES <= STANDARD_PREFIXES
    assert "us-gaap" in CORE_PREFIXES and "dei" in CORE_PREFIXES
    assert "srt" in STANDARD_PREFIXES and "srt" not in CORE_PREFIXES


def test_linkbase_bundle_definition_arcs_default_empty():
    assert LinkbaseBundle().definition_arcs == ()


def test_definition_arc_optional_defaults():
    arc = DefinitionArc(
        parent_qname="srt:ProductOrServiceAxis",
        child_qname="srt:ProductsAndServicesDomain",
        arcrole="http://xbrl.org/int/dim/arcrole/dimension-domain",
    )
    assert arc.order is None
    assert arc.role_uri is None
    assert arc.usable is None
    assert arc.closed is None
    assert arc.context_element is None
    assert arc.target_role is None
