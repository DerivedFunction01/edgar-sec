"""Unit tests for independent accounting conservation identities."""

from tests.support import fixture_path
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.identities import (
    verify_all_accounting_identities,
    verify_balance_sheet_identity,
    verify_dimensional_rollup,
    verify_gross_profit_identity,
)
from edgar_sec.engine.xbrl.instance_parser import parse_instance_facts
from edgar_sec.engine.xbrl.models import XbrlFact


def test_balance_sheet_identity_from_parsed_facts() -> None:
    """Verify Assets == Liabilities + Equity holds on real parsed facts."""
    xml_data = fixture_path("xbrl/msft-20240630_htm.xml").read_bytes()
    facts = parse_instance_facts(xml_data, "0000950170-24-087843")

    outcome = verify_balance_sheet_identity(facts)
    assert outcome is not None
    assert outcome.passed
    assert outcome.lhs_value == 512163000000.0
    assert outcome.rhs_value == 512163000000.0
    assert outcome.discrepancy == 0.0


def test_gross_profit_identity_from_parsed_facts() -> None:
    """Verify GrossProfit == Revenues - COGS holds on real parsed facts."""
    xml_data = fixture_path("xbrl/msft-20240630_htm.xml").read_bytes()
    facts = parse_instance_facts(xml_data, "0000950170-24-087843")

    outcome = verify_gross_profit_identity(facts)
    assert outcome is not None
    assert outcome.passed
    assert outcome.lhs_value == 169295000000.0
    assert outcome.rhs_value == 169295000000.0
    assert outcome.discrepancy == 0.0


def test_dimensional_rollup_identity() -> None:
    """Verify dimensional member sum matches consolidated total."""
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(
            accession=acc,
            concept_qname="us-gaap:Revenues",
            value=100.0,
            dimensions={},
        ),
        XbrlFact(
            accession=acc,
            concept_qname="us-gaap:Revenues",
            value=60.0,
            dimensions={"axis": "segA"},
        ),
        XbrlFact(
            accession=acc,
            concept_qname="us-gaap:Revenues",
            value=40.0,
            dimensions={"axis": "segB"},
        ),
    ]

    outcome = verify_dimensional_rollup(facts, "us-gaap:Revenues", "axis")
    assert outcome is not None
    assert outcome.passed
    assert outcome.lhs_value == 100.0
    assert outcome.rhs_value == 100.0
    assert outcome.discrepancy == 0.0


def test_verify_all_accounting_identities() -> None:
    """Verify comprehensive conservation evaluation across statements."""
    xml_data = fixture_path("xbrl/msft-20240630_htm.xml").read_bytes()
    facts = parse_instance_facts(xml_data, "0000950170-24-087843")

    results = verify_all_accounting_identities(facts)
    assert len(results) >= 2
    assert all(r.passed for r in results)
