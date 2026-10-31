"""Tests for seeded longitudinal relations and their evaluation."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.review.relations import (
    RELATION_SET,
    RelationSpec,
    evaluate_relations,
)
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import FinancialQueryEngine
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import fixture_path


def test_relation_set_entries_record_the_concept_switch() -> None:
    """Every relation names its boundary and both endpoints' own concepts."""
    assert RELATION_SET
    for spec in RELATION_SET:
        assert spec.provenance
        assert spec.boundary
        assert spec.pre_concept != spec.post_concept
        assert spec.pre_accession != spec.post_accession
        assert spec.pre_value > 0 and spec.post_value > 0


def _relation_engine():
    """A query engine over the fixture taxonomy for relation tests."""
    tax = load_domain_taxonomy(fixture_path("xbrl/taxonomy"))
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    return FinancialQueryEngine(XbrlConstraintSolver(kb))


def test_evaluate_relations_synthetic() -> None:
    """A relation holds when each endpoint answers under its own concept."""

    def fact(accession: str, qname: str, value: float, instant: str) -> XbrlFact:
        return XbrlFact(
            accession=AccessionNumber.from_any(accession),
            concept_qname=qname,
            value=value,
            unit="USD",
            period_type="instant",
            instant_date=instant,
        )

    pre_acc, post_acc = "0000000001-11-000001", "0000000001-24-000002"
    cash = "us-gaap:CashAndCashEquivalentsAtCarryingValue"
    rollup = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
    spec = RelationSpec(
        firm="BAC",
        boundary="ASU 2016-18",
        pre_concept=cash,
        pre_value=100.0,
        pre_instant="2011-12-31",
        pre_accession=pre_acc,
        post_concept=rollup,
        post_value=200.0,
        post_instant="2024-12-31",
        post_accession=post_acc,
        provenance="synthetic specimen",
    )
    endpoints = {
        pre_acc: ((fact(pre_acc, cash, 100.0, "2011-12-31"),), ()),
        post_acc: ((fact(post_acc, rollup, 200.0, "2024-12-31"),), ()),
    }
    engine = _relation_engine()
    report = evaluate_relations(engine, endpoints, (spec,))
    assert report.passed_all
    assert report.passed == 1
    moved = {
        pre_acc: ((fact(pre_acc, cash, 101.0, "2011-12-31"),), ()),
        post_acc: endpoints[post_acc],
    }
    failed = evaluate_relations(engine, moved, (spec,))
    assert not failed.passed_all
    assert "ASU 2016-18" in failed.failures[0]
