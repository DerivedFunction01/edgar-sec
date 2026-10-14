"""Unit tests for calculation, presentation, label, and schema linkbase parsers."""

from tests.support import fixture_path
from edgar_sec.engine.xbrl.linkbase_parser import (
    parse_calculation_linkbase,
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


def test_parse_linkbase_bundle() -> None:
    """Verify unified LinkbaseBundle aggregation."""
    cal_xml = fixture_path("xbrl/msft-20240630_cal.xml").read_bytes()
    pre_xml = fixture_path("xbrl/msft-20240630_pre.xml").read_bytes()
    bundle = parse_linkbase_bundle(cal_xml=cal_xml, pre_xml=pre_xml)
    assert len(bundle.calculation_arcs) == 4
    assert len(bundle.presentation_arcs) == 2
    assert len(bundle.labels) == 0
