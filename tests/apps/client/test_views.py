"""Tests for statement view status over composed graphs."""

from edgar_sec.apps.client.views import StatementView
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.solve.statement import build_statement_graph
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def _fact(qname: str, value: float) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any("0000063908-25-000012"),
        concept_qname=qname,
        value=value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        dimensions={},
    )


def _arcs() -> tuple[CalculationArc, ...]:
    return (
        CalculationArc(
            parent_qname="us-gaap:GrossProfit",
            child_qname="us-gaap:Revenues",
            weight=1.0,
            order=1.0,
            role_uri="",
        ),
        CalculationArc(
            parent_qname="us-gaap:GrossProfit",
            child_qname="us-gaap:CostOfGoodsAndServicesSold",
            weight=-1.0,
            order=2.0,
            role_uri="",
        ),
    )


def test_view_status_derived_when_root_gap_filled() -> None:
    """Verify a face whose root total is gap-filled reports DERIVED."""
    graph = build_statement_graph(
        root_concept="us-gaap:GrossProfit",
        statement_type="Income Statement",
        facts=(
            _fact("us-gaap:Revenues", 300.0),
            _fact("us-gaap:CostOfGoodsAndServicesSold", 120.0),
        ),
        arcs=_arcs(),
        taxonomy=load_domain_taxonomy(),
        period_type="duration",
    )
    assert StatementView(graph).status is QueryStatus.DERIVED


def test_view_status_reported_when_root_filed() -> None:
    """Verify a face whose root total is filed reports REPORTED."""
    graph = build_statement_graph(
        root_concept="us-gaap:GrossProfit",
        statement_type="Income Statement",
        facts=(
            _fact("us-gaap:GrossProfit", 180.0),
            _fact("us-gaap:Revenues", 300.0),
            _fact("us-gaap:CostOfGoodsAndServicesSold", 120.0),
        ),
        arcs=_arcs(),
        taxonomy=load_domain_taxonomy(),
        period_type="duration",
    )
    assert StatementView(graph).status is QueryStatus.REPORTED
