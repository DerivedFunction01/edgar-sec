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
