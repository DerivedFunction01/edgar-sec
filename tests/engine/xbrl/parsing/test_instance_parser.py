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
    """AAPL-style four RPO buckets parse as four distinct dimensioned contexts."""
    buckets = (
        ("0.64", "2024-09-29"),
        ("0.25", "2025-09-28"),
        ("0.09", "2026-09-27"),
        ("0.02", "2027-09-26"),
    )
    contexts = "".join(
        f'<context id="c-{i}"><entity><identifier scheme="http://www.sec.gov/CIK">1'
        "</identifier><segment>"
        f'<xbrldi:typedMember dimension="{_TYPED_AXIS}">'
        f"<us-gaap:{_TYPED_AXIS.split(':')[-1]}.domain>{date}"
        f"</us-gaap:{_TYPED_AXIS.split(':')[-1]}.domain></xbrldi:typedMember>"
        "</segment></entity><period><instant>2024-09-28</instant></period></context>"
        for i, (_, date) in enumerate(buckets)
    )
    facts_xml = "".join(
        "<us-gaap:RevenueRemainingPerformanceObligationPercentage "
        f'contextRef="c-{i}" unitRef="p" decimals="2">{value}'
        "</us-gaap:RevenueRemainingPerformanceObligationPercentage>"
        for i, (value, _) in enumerate(buckets)
    )
    xml = (
        '<xbrl xmlns="http://www.xbrl.org/2003/instance" '
        'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        'xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
        f"{contexts}"
        '<unit id="p"><measure>pure</measure></unit>'
        f"{facts_xml}</xbrl>"
    ).encode()
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


def _facts_document(*fact_elements: str) -> bytes:
    return (
        '<xbrl xmlns="http://www.xbrl.org/2003/instance" '
        'xmlns:us-gaap="http://fasb.org/us-gaap/2024" '
        'xmlns:iso4217="http://www.xbrl.org/2003/iso4217">'
        '<context id="c-1"><entity><identifier scheme="http://www.sec.gov/CIK">1'
        "</identifier></entity>"
        "<period><instant>2024-09-28</instant></period></context>"
        '<context id="c-2"><entity><identifier scheme="http://www.sec.gov/CIK">1'
        "</identifier></entity>"
        "<period><instant>2023-09-30</instant></period></context>"
        '<unit id="u"><measure>iso4217:USD</measure></unit>'
        f"{''.join(fact_elements)}</xbrl>"
    ).encode()


def _assets_element(value: str, decimals: str, context: str = "c-1") -> str:
    return (
        f'<us-gaap:Assets contextRef="{context}" unitRef="u" '
        f'decimals="{decimals}">{value}</us-gaap:Assets>'
    )


def test_exact_duplicate_facts_collapse() -> None:
    """The same fact element twice parses to a single fact."""
    xml = _facts_document(_assets_element("100", "0"), _assets_element("100", "0"))
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    assert len(facts) == 1
    assert facts[0].value == 100.0


def test_duplicate_facts_keep_most_precise_occurrence() -> None:
    """Among duplicates differing only in decimals, the highest wins."""
    xml = _facts_document(
        _assets_element("100", "0"),
        _assets_element("100", "3"),
        _assets_element("100", "1"),
    )
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    assert len(facts) == 1
    assert facts[0].decimals == 3


def test_conflicting_values_at_same_identity_are_preserved() -> None:
    """Duplicates with different values stay as separate facts."""
    xml = _facts_document(_assets_element("100", "0"), _assets_element("200", "0"))
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    assert [fact.value for fact in facts] == [100.0, 200.0]


def test_non_duplicate_facts_are_untouched() -> None:
    """Facts differing in concept or context are all retained."""
    xml = _facts_document(
        _assets_element("100", "0"),
        _assets_element("100", "0", context="c-2"),
        '<us-gaap:Liabilities contextRef="c-1" unitRef="u" decimals="0">'
        "40</us-gaap:Liabilities>",
    )
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    assert len(facts) == 3


def _cover_document(*fact_elements: str) -> bytes:
    return (
        '<xbrl xmlns="http://www.xbrl.org/2003/instance" '
        'xmlns:dei="http://xbrl.sec.gov/dei/2024" '
        'xmlns:us-gaap="http://fasb.org/us-gaap/2024" '
        'xmlns:ex="http://example.com/2024">'
        '<context id="c-1"><entity><identifier scheme="http://www.sec.gov/CIK">1'
        "</identifier></entity>"
        "<period><instant>2024-09-28</instant></period></context>"
        f"{''.join(fact_elements)}</xbrl>"
    ).encode()


def test_declared_non_numeric_facts_stay_strings() -> None:
    """CIK and fiscal-year cover facts are not float-sniffed into numbers."""
    xml = _cover_document(
        '<dei:EntityCentralIndexKey contextRef="c-1">0000320193'
        "</dei:EntityCentralIndexKey>",
        '<dei:DocumentFiscalYearFocus contextRef="c-1">2024'
        "</dei:DocumentFiscalYearFocus>",
    )
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    by_qname = {fact.concept_qname: fact.value for fact in facts}
    assert by_qname == {
        "dei:EntityCentralIndexKey": "0000320193",
        "dei:DocumentFiscalYearFocus": "2024",
    }


def test_declared_numeric_facts_stay_numeric() -> None:
    """Shares, monetary, and decimal declarations still parse as floats."""
    xml = _cover_document(
        '<dei:EntityCommonStockSharesOutstanding contextRef="c-1">1000'
        "</dei:EntityCommonStockSharesOutstanding>",
        '<us-gaap:Assets contextRef="c-1">200</us-gaap:Assets>',
    )
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    by_qname = {fact.concept_qname: fact.value for fact in facts}
    assert by_qname == {
        "dei:EntityCommonStockSharesOutstanding": 1000.0,
        "us-gaap:Assets": 200.0,
    }


def test_supplied_numeric_declaration_stays_numeric() -> None:
    """A supplied decimal declaration parses its fact as a float."""
    xml = _cover_document('<ex:Rate contextRef="c-1">0.25</ex:Rate>')
    facts = parse_instance_facts(
        xml,
        AccessionNumber("0000320193-24-000123"),
        {"ex:Rate": "xbrli:decimalItemType"},
    )
    assert facts[0].value == 0.25


def test_undeclared_concept_keeps_float_sniff_fallback() -> None:
    """A concept with no declaration anywhere parses exactly as before."""
    xml = _cover_document('<ex:CustomMetric contextRef="c-1">12.5</ex:CustomMetric>')
    facts = parse_instance_facts(xml, AccessionNumber("0000320193-24-000123"))
    assert facts[0].value == 12.5


def test_supplied_item_types_override_the_archive() -> None:
    """A supplied map wins over the archive vintage the instance declares."""
    xml = _cover_document('<us-gaap:Assets contextRef="c-1">100</us-gaap:Assets>')
    facts = parse_instance_facts(
        xml,
        AccessionNumber("0000320193-24-000123"),
        {"us-gaap:Assets": "xbrli:stringItemType"},
    )
    assert facts[0].value == "100"


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
