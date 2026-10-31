"""Tests for the seeded answerability battery and its evaluation."""

from collections import Counter

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.review.battery import BATTERY_SET, evaluate_battery
from edgar_sec.engine.xbrl.review.battery_entries import (
    BASIC,
    COMPLEX,
    TEXTBOOK,
    BatteryEntry,
)
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import FinancialQueryEngine
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import fixture_path


def test_battery_set_shape() -> None:
    """Every entry is identified, tiered, scoped, and carries provenance."""
    assert BATTERY_SET
    ids = [entry.entry_id for entry in BATTERY_SET]
    assert len(ids) == len(set(ids))
    counts = Counter(entry.tier for entry in BATTERY_SET)
    assert counts[BASIC] >= 30
    assert counts[TEXTBOOK] >= 25
    assert counts[COMPLEX] >= 6
    firms = {entry.firm for entry in BATTERY_SET if entry.tier == BASIC}
    assert len(firms) >= 8
    for entry in BATTERY_SET:
        assert entry.verification
        assert len(entry.accession) == 20
        assert ":" in entry.qname
        assert bool(entry.instant) != bool(entry.start and entry.end)


def _battery_engine() -> FinancialQueryEngine:
    """A query engine over the fixture taxonomy for battery tests."""
    tax = load_domain_taxonomy(fixture_path("xbrl/taxonomy"))
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    return FinancialQueryEngine(XbrlConstraintSolver(kb))


def _fact(accession: str, qname: str, value: float, instant: str) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname=qname,
        value=value,
        unit="USD",
        period_type="instant",
        instant_date=instant,
    )


_ACC = "0000000001-24-000001"
_ENTRY = BatteryEntry(
    entry_id="synthetic-cash",
    tier=BASIC,
    firm="SYN",
    accession=_ACC,
    qname="us-gaap:CashAndCashEquivalentsAtCarryingValue",
    expected_value=42.0,
    instant="2024-12-31",
    verification="synthetic",
)


def test_evaluate_battery_passes_at_verified_value() -> None:
    """An entry passes when the engine reports its verified value."""
    facts = (_fact(_ACC, _ENTRY.qname, 42.0, "2024-12-31"),)
    report = evaluate_battery(_battery_engine(), {_ACC: (facts, ())}, (_ENTRY,))
    assert report.passed_all
    assert report.results[0].actual_status == "REPORTED"


def test_evaluate_battery_fails_on_wrong_value() -> None:
    """A value mismatch fails the entry and names both values."""
    facts = (_fact(_ACC, _ENTRY.qname, 41.0, "2024-12-31"),)
    report = evaluate_battery(_battery_engine(), {_ACC: (facts, ())}, (_ENTRY,))
    assert not report.passed_all
    assert "42.0" in report.failures[0] and "41.0" in report.failures[0]


def test_evaluate_battery_fails_without_endpoint() -> None:
    """A missing endpoint fails the entry instead of skipping it."""
    report = evaluate_battery(_battery_engine(), {}, (_ENTRY,))
    assert not report.passed_all
    assert report.results[0].actual_status == "NO_ENDPOINT"
