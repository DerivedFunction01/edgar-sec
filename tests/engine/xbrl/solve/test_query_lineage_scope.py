"""Tests for amendment-lineage scoping of concept queries."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import FinancialQuery, QueryStatus
from edgar_sec.engine.xbrl.solve.scoping import (
    FactScope,
    FilingRef,
    build_lineages,
)
from .query_fixtures import _query_engine


_AMD_ORIG = "0000007084-23-000028"
_AMD_AMEND = "0000007084-23-000033"


def _amendment_pair() -> tuple:
    """An original 10-Q fact and its 10-Q/A restatement of the same key."""
    lineage = build_lineages(
        [
            FilingRef(_AMD_ORIG, "7084", "10-Q", "2023-06-30", "2023-08-01"),
            FilingRef(_AMD_AMEND, "7084", "10-Q/A", "2023-06-30", "2023-11-01"),
        ]
    )[0]

    def fact(accession: str, value: float) -> XbrlFact:
        return XbrlFact(
            accession=AccessionNumber.from_any(accession),
            concept_qname="us-gaap:NetIncomeLoss",
            value=value,
            unit="USD",
            period_type="duration",
            start_date="2023-04-01",
            end_date="2023-06-30",
        )

    return lineage, (fact(_AMD_ORIG, 100.0), fact(_AMD_AMEND, 120.0))


def test_pooled_scope_without_lineage_stays_refused() -> None:
    _, facts = _amendment_pair()
    scope = FactScope(start_date="2023-04-01", end_date="2023-06-30")
    result = _query_engine().execute(
        FinancialQuery("us-gaap:NetIncomeLoss", scope), facts
    )
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None


def test_lineage_scope_answers_from_the_restated_population() -> None:
    lineage, facts = _amendment_pair()
    scope = FactScope(
        start_date="2023-04-01", end_date="2023-06-30", lineages=(lineage,)
    )
    result = _query_engine().execute(
        FinancialQuery("us-gaap:NetIncomeLoss", scope), facts
    )
    assert result.status == QueryStatus.REPORTED
    assert result.value == 120.0
    assert result.provenance == _AMD_AMEND


def test_lineage_scope_with_an_unrelated_filing_stays_refused() -> None:
    lineage, facts = _amendment_pair()
    outsider = XbrlFact(
        accession=AccessionNumber.from_any("0000019617-23-000270"),
        concept_qname="us-gaap:NetIncomeLoss",
        value=7.0,
        unit="USD",
        period_type="duration",
        start_date="2023-04-01",
        end_date="2023-06-30",
    )
    scope = FactScope(
        start_date="2023-04-01", end_date="2023-06-30", lineages=(lineage,)
    )
    result = _query_engine().execute(
        FinancialQuery("us-gaap:NetIncomeLoss", scope), (*facts, outsider)
    )
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None
