"""Unit tests for XBRL instance document facts, contexts, and dimensional coordinates."""

from tests.support import fixture_path
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.parsing.instance_parser import parse_instance_facts


def test_parse_instance_facts() -> None:
    """Verify instance fact extraction, dimensional slices, and exact values."""
    xml_data = fixture_path("xbrl/msft-20240630_htm.xml").read_bytes()
    accession = AccessionNumber("0000950170-24-087843")
    facts = parse_instance_facts(xml_data, accession)

    assert len(facts) == 8

    rev_fact = next(
        f
        for f in facts
        if f.concept_qname
        == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        and not f.dimensions
    )
    assert rev_fact.value == 245122000000.0
    assert rev_fact.unit == "USD"
    assert rev_fact.period_type == "duration"
    assert rev_fact.start_date == "2023-07-01"
    assert rev_fact.end_date == "2024-06-30"

    cloud_fact = next(
        f
        for f in facts
        if f.concept_qname
        == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        and f.dimensions
    )
    assert cloud_fact.value == 97726000000.0
    assert (
        cloud_fact.dimensions.get("srt:ProductOrServiceAxis")
        == "msft:ServerProductsAndCloudServicesMember"
    )

    assets_fact = next(f for f in facts if f.concept_qname == "us-gaap:Assets")
    assert assets_fact.value == 512163000000.0
    assert assets_fact.period_type == "instant"
    assert assets_fact.instant_date == "2024-06-30"


_TYPED_AXIS = (
    "us-gaap:RevenueRemainingPerformanceObligation"
    "ExpectedTimingOfSatisfactionStartDateAxis"
)


def _instance_xml(context_inner: str) -> bytes:
    return (
        '<xbrl xmlns="http://www.xbrl.org/2003/instance" '
        'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        'xmlns:us-gaap="http://fasb.org/us-gaap/2024" '
        'xmlns:srt="http://fasb.org/srt/2024" '
        'xmlns:ex="http://example.com/2024">'
        f'<context id="c-1"><entity><identifier scheme="http://www.sec.gov/CIK">1'
        f"</identifier><segment>{context_inner}</segment></entity>"
        "<period><instant>2024-09-28</instant></period></context>"
        '<unit id="p"><measure>pure</measure></unit>'
        "<us-gaap:RevenueRemainingPerformanceObligationPercentage "
        'contextRef="c-1" unitRef="p" decimals="2">0.64'
        "</us-gaap:RevenueRemainingPerformanceObligationPercentage></xbrl>"
    ).encode()


def test_typed_member_dimension_captured() -> None:
    """Typed member value is the element's literal text content."""
    xml = _instance_xml(
        f'<xbrldi:typedMember dimension="{_TYPED_AXIS}">'
        f"<us-gaap:{_TYPED_AXIS.split(':')[-1]}.domain>2024-09-29"
        f"</us-gaap:{_TYPED_AXIS.split(':')[-1]}.domain></xbrldi:typedMember>"
    )
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    assert len(facts) == 1
    assert facts[0].dimensions == {_TYPED_AXIS: "2024-09-29"}
    assert facts[0].value == 0.64


def test_typed_member_free_text_value() -> None:
    """Free-text typed members are carried verbatim, not as qnames."""
    xml = _instance_xml(
        '<xbrldi:typedMember dimension="us-gaap:ReinsuranceContractAxis">'
        "<us-gaap:ReinsuranceContractAxis.domain>Member Loss Recoupments"
        "</us-gaap:ReinsuranceContractAxis.domain></xbrldi:typedMember>"
    )
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    assert facts[0].dimensions == {
        "us-gaap:ReinsuranceContractAxis": "Member Loss Recoupments"
    }


def test_mixed_explicit_and_typed_context() -> None:
    """A context carrying both member kinds yields both dimensions."""
    xml = _instance_xml(
        '<xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">'
        "ex:SomeMember</xbrldi:explicitMember>"
        f'<xbrldi:typedMember dimension="{_TYPED_AXIS}">'
        f"<us-gaap:{_TYPED_AXIS.split(':')[-1]}.domain>2025-09-28"
        f"</us-gaap:{_TYPED_AXIS.split(':')[-1]}.domain></xbrldi:typedMember>"
    )
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    assert facts[0].dimensions == {
        "srt:ProductOrServiceAxis": "ex:SomeMember",
        _TYPED_AXIS: "2025-09-28",
    }


def test_aapl_rpo_specimen_contexts() -> None:
    """AAPL's four RPO buckets parse as four distinct dimensioned contexts."""
    import zipfile

    zip_path = fixture_path("xbrl/seed/aapl_2024_10k/aapl_filing.zip")
    with zipfile.ZipFile(zip_path) as zf:
        xml = zf.read("0000320193-24-000123/aapl-20240928_htm.xml")
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    rpo = [
        f
        for f in facts
        if f.concept_qname == "us-gaap:RevenueRemainingPerformanceObligationPercentage"
    ]
    by_value = {f.value: f.dimensions.get(_TYPED_AXIS) for f in rpo}
    assert by_value == {
        0.64: "2024-09-29",
        0.25: "2025-09-28",
        0.09: "2026-09-27",
        0.02: "2027-09-26",
    }


def test_extract_units_divide() -> None:
    """Verify divide unit parsing preserves numerator and denominator."""
    import xml.etree.ElementTree as ET
    from edgar_sec.engine.xbrl.parsing.instance_parser import _extract_units

    xml = (
        b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        b'xmlns:iso4217="http://www.xbrl.org/2003/iso4217">'
        b'<xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
        b'<xbrli:unit id="usdPerShare"><xbrli:divide>'
        b"<xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>"
        b"<xbrli:unitDenominator><xbrli:measure>shares</xbrli:measure></xbrli:unitDenominator>"
        b"</xbrli:divide></xbrli:unit></xbrli:xbrl>"
    )
    units = _extract_units(ET.fromstring(xml))
    assert units["USD"] == "USD"
    assert units["usdPerShare"] == "USD/shares"
