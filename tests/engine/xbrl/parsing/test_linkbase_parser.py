"""Unit tests for calculation, presentation, label, definition, and schema parsers."""

from tests.support import fixture_path
from edgar_sec.engine.xbrl.parsing.linkbase_parser import (
    parse_calculation_linkbase,
    parse_definition_linkbase,
    parse_label_linkbase,
    parse_linkbase_bundle,
    parse_presentation_linkbase,
    parse_schema_declarations,
)


def test_parse_calculation_linkbase() -> None:
    """Verify calculation arc extraction and summation weights."""
    cal_xml = fixture_path("xbrl/msft-20240630_cal.xml").read_bytes()
    arcs = parse_calculation_linkbase(cal_xml)
    assert len(arcs) == 4

    gp_rev = next(
        a
        for a in arcs
        if a.parent_qname == "us-gaap:GrossProfit"
        and a.child_qname
        == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert gp_rev.weight == 1.0

    gp_cogs = next(
        a
        for a in arcs
        if a.parent_qname == "us-gaap:GrossProfit"
        and a.child_qname == "us-gaap:CostOfGoodsAndServicesSold"
    )
    assert gp_cogs.weight == -1.0


def test_parse_presentation_linkbase() -> None:
    """Verify presentation hierarchy and parent-child display orders."""
    pre_xml = fixture_path("xbrl/msft-20240630_pre.xml").read_bytes()
    arcs = parse_presentation_linkbase(pre_xml)
    assert len(arcs) == 2
    assert arcs[0].parent_qname == "us-gaap:IncomeStatementAbstract"
    assert arcs[0].child_qname == "us-gaap:GrossProfit"
    assert arcs[0].order == 1.0


def test_parse_label_linkbase() -> None:
    """Verify label resource extraction and concept mapping."""
    lab_xml = fixture_path("xbrl/msft-20240630_lab.xml").read_bytes()
    labels = parse_label_linkbase(lab_xml)
    assert len(labels) == 2

    gp_label = next(lbl for lbl in labels if lbl.concept_qname == "us-gaap:GrossProfit")
    assert gp_label.label == "Gross Profit"


def test_parse_schema_declarations() -> None:
    """Verify taxonomy extension schema declarations extraction."""
    xsd = fixture_path("xbrl/msft-20240630.xsd").read_bytes()
    decls = parse_schema_declarations(xsd, target_prefix="msft")
    assert len(decls) == 2
    assert decls[0].concept_qname == "msft:ServerProductsAndCloudServicesMember"
    assert decls[0].period_type == "duration"
    assert decls[0].item_type == "xbrli:stringItemType"


def test_parse_schema_declarations_without_type() -> None:
    """An element with no type attribute declares item_type None."""
    xsd = (
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'targetNamespace="http://example.com/20240101">'
        '<xs:element name="UntypedMember" substitutionGroup="xbrli:item"/>'
        "</xs:schema>"
    )
    decls = parse_schema_declarations(xsd, target_prefix="ex")
    assert len(decls) == 1
    assert decls[0].item_type is None


def test_parse_definition_linkbase() -> None:
    """Verify definition arc extraction and dimensional attributes."""
    def_xml = fixture_path("xbrl/msft-20240630_def.xml").read_bytes()
    arcs = parse_definition_linkbase(def_xml)
    assert len(arcs) == 7

    dim_domain = next(
        a
        for a in arcs
        if a.arcrole == "http://xbrl.org/int/dim/arcrole/dimension-domain"
    )
    assert dim_domain.parent_qname == "srt:ProductOrServiceAxis"
    assert dim_domain.child_qname == "srt:ProductsAndServicesDomain"
    assert dim_domain.order == 1.0
    assert dim_domain.role_uri == "http://www.microsoft.com/role/SegmentInformation"
    assert dim_domain.usable is None
    assert dim_domain.closed is None
    assert dim_domain.context_element is None
    assert dim_domain.target_role is None

    dim_default = next(
        a
        for a in arcs
        if a.arcrole == "http://xbrl.org/int/dim/arcrole/dimension-default"
    )
    assert dim_default.parent_qname == "srt:ProductOrServiceAxis"
    assert dim_default.child_qname == "srt:ProductsAndServicesDomain"

    hypercube = next(
        a
        for a in arcs
        if a.arcrole == "http://xbrl.org/int/dim/arcrole/hypercube-dimension"
    )
    assert hypercube.parent_qname == "us-gaap:StatementTable"
    assert hypercube.child_qname == "srt:ProductOrServiceAxis"

    all_arc = next(
        a for a in arcs if a.arcrole == "http://xbrl.org/int/dim/arcrole/all"
    )
    assert all_arc.parent_qname == "us-gaap:StatementLineItems"
    assert all_arc.child_qname == "us-gaap:StatementTable"
    assert all_arc.closed is True
    assert all_arc.context_element == "segment"

    nested = next(
        a for a in arcs if a.parent_qname == "msft:ServerProductsAndCloudServicesMember"
    )
    assert nested.arcrole == "http://xbrl.org/int/dim/arcrole/domain-member"
    assert nested.child_qname == "msft:ProductAndServiceOtherMember"

    unusable = next(a for a in arcs if a.child_qname == "us-gaap:ProductMember")
    assert unusable.arcrole == "http://xbrl.org/int/dim/arcrole/domain-member"
    assert unusable.parent_qname == "srt:ProductsAndServicesDomain"
    assert unusable.usable is False
    assert unusable.order == 2.0


def test_parse_linkbase_bundle() -> None:
    """Verify unified LinkbaseBundle aggregation."""
    cal_xml = fixture_path("xbrl/msft-20240630_cal.xml").read_bytes()
    pre_xml = fixture_path("xbrl/msft-20240630_pre.xml").read_bytes()
    bundle = parse_linkbase_bundle(cal_xml=cal_xml, pre_xml=pre_xml)
    assert len(bundle.calculation_arcs) == 4
    assert len(bundle.presentation_arcs) == 2
    assert len(bundle.labels) == 0
    assert bundle.definition_arcs == ()


def test_parse_linkbase_bundle_with_def_xml() -> None:
    """Verify a bundle carries definition arcs from an explicit def source."""
    def_xml = fixture_path("xbrl/msft-20240630_def.xml").read_bytes()
    bundle = parse_linkbase_bundle(def_xml=def_xml)
    assert len(bundle.definition_arcs) == 7


def test_parse_linkbase_bundle_def_fallback_to_xsd() -> None:
    """Verify definition arcs fall back to an embedded schema definitionLink."""
    xsd = (
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:link="http://www.xbrl.org/2003/linkbase" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xmlns:xbrldt="http://xbrl.org/2005/xbrldt" '
        'targetNamespace="http://example.com/20240101">'
        '<link:definitionLink xlink:type="extended" '
        'xlink:role="http://example.com/role/Test">'
        '<link:loc xlink:type="locator" '
        'xlink:href="https://xbrl.fasb.org/srt/2024/elts/srt-2024.xsd#srt_ProductOrServiceAxis" '
        'xlink:label="loc_Axis"/>'
        '<link:loc xlink:type="locator" '
        'xlink:href="https://xbrl.fasb.org/srt/2024/elts/srt-2024.xsd#srt_ProductsAndServicesDomain" '
        'xlink:label="loc_Domain"/>'
        '<link:definitionArc xlink:type="arc" '
        'xlink:arcrole="http://xbrl.org/int/dim/arcrole/dimension-domain" '
        'xlink:from="loc_Axis" xlink:to="loc_Domain" order="1"/>'
        "</link:definitionLink></xs:schema>"
    )
    bundle = parse_linkbase_bundle(xsd=xsd)
    assert len(bundle.definition_arcs) == 1
    arc = bundle.definition_arcs[0]
    assert arc.parent_qname == "srt:ProductOrServiceAxis"
    assert arc.child_qname == "srt:ProductsAndServicesDomain"
    assert arc.arcrole == "http://xbrl.org/int/dim/arcrole/dimension-domain"
    assert arc.role_uri == "http://example.com/role/Test"
