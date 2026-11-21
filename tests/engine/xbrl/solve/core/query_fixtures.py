"""Shared fixtures for the scoped-query suites."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.core.query import (
    FinancialQuery,
    FinancialQueryEngine,
    FinancialQueryResult,
)
from edgar_sec.engine.xbrl.solve.core.scoping import FactScope
from edgar_sec.engine.xbrl.solve.core.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def _query_engine(declarations=None) -> FinancialQueryEngine:
    return FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=load_domain_taxonomy())),
        declarations=declarations,
    )


def _table_declarations(*qnames: str) -> dict:
    """Declarations for standard qnames from the shipped item-type table."""
    from edgar_sec.engine.xbrl.taxonomy.archive import current_table
    from edgar_sec.engine.xbrl.taxonomy.item_types import declaration_for

    table = current_table()
    return {
        qname: declaration
        for qname in qnames
        if (declaration := declaration_for(qname, table)) is not None
    }


def _instant_usd_fact(qname: str, value: float, decimals: int | None) -> XbrlFact:
    return XbrlFact(
        AccessionNumber("0000950170-24-087843"),
        qname,
        value,
        unit="USD",
        decimals=decimals,
        period_type="instant",
        instant_date="2024-06-30",
    )


def _reported_result(facts: tuple[XbrlFact, ...], qname: str) -> FinancialQueryResult:
    return _query_engine().execute(
        FinancialQuery(
            qname,
            FactScope(
                accession="0000950170-24-087843",
                instant_date="2024-06-30",
                unit="USD",
            ),
        ),
        facts,
    )


def _duration_fact(qname: str, value: float) -> XbrlFact:
    return XbrlFact(
        AccessionNumber("0000950170-24-087843"),
        qname,
        value,
        unit="USD",
        period_type="duration",
        start_date="2023-07-01",
        end_date="2024-06-30",
    )


_DURATION_SCOPE = FactScope(
    accession="0000950170-24-087843",
    start_date="2023-07-01",
    end_date="2024-06-30",
    unit="USD",
)


def _instant_fact(qname: str, value: float) -> XbrlFact:
    return XbrlFact(
        AccessionNumber("0000950170-24-087843"),
        qname,
        value,
        unit="USD",
        period_type="instant",
        instant_date="2024-06-30",
    )


_INSTANT_SCOPE = FactScope(
    accession="0000950170-24-087843",
    instant_date="2024-06-30",
    unit="USD",
)


def _duration_usd_fact(qname: str, value: float, unit: str = "USD") -> XbrlFact:
    return XbrlFact(
        AccessionNumber("0000950170-24-087843"),
        qname,
        value,
        unit=unit,
        period_type="duration",
        start_date="2023-07-01",
        end_date="2024-06-30",
    )


def _text_fact(qname: str, text: str) -> XbrlFact:
    return XbrlFact(
        AccessionNumber("0000950170-24-087843"),
        qname,
        text,
        period_type="duration",
        start_date="2023-07-01",
        end_date="2024-06-30",
    )
