"""Shared facade factories and synthetic-fact builders for the XBRL client suites."""

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import (
    ConceptLabel,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.core.query import (
    FinancialQuery,
    FinancialQueryEngine,
    FinancialQueryResult,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.core.scoping import FactScope
from edgar_sec.engine.xbrl.solve.core.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.statements.statement import StatementGraph
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
    seed_folder,
)


_MSFT_ACCESSION = "0000950170-24-087843"
_STANDARD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
_TERSE_LABEL_ROLE = "http://www.xbrl.org/2003/role/terseLabel"


def _create_xbrl_facade(firm: str) -> Xbrl:
    facts = load_seed_facts(seed_folder(firm))
    arcs = load_seed_calculation_arcs(seed_folder(firm))
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def _create_labelled_xbrl_facade() -> Xbrl:
    facts = load_seed_facts("msft_2024_10k")
    arcs = load_seed_calculation_arcs("msft_2024_10k")
    labels = (
        ConceptLabel(
            concept_qname="us-gaap:Assets",
            role_uri=_STANDARD_LABEL_ROLE,
            label="Total Assets (Standard)",
            lang="en-US",
        ),
        ConceptLabel(
            concept_qname="us-gaap:Assets",
            role_uri=_TERSE_LABEL_ROLE,
            label="Terse Assets",
            lang="en-US",
        ),
        ConceptLabel(
            concept_qname="us-gaap:Assets",
            role_uri=_STANDARD_LABEL_ROLE,
            label="Actifs Totaux",
            lang="fr-FR",
        ),
        ConceptLabel(
            concept_qname="us-gaap:AssetsCurrent",
            role_uri=_TERSE_LABEL_ROLE,
            label="Current Assets (Terse)",
            lang="en-US",
        ),
    )
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs, labels=labels),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def _oracle_query(
    term: str, scope: FactScope, mode: QueryMode = QueryMode.REPORTED_ONLY
) -> FinancialQueryResult:
    engine = FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(load_domain_taxonomy()))
    )
    return engine.execute(
        FinancialQuery(term, scope, mode=mode),
        load_seed_facts("msft_2024_10k"),
        load_seed_calculation_arcs("msft_2024_10k"),
    )


_SYNTHETIC_ACCESSION = "0000000001-23-000001"
_ANNUAL = ("2023-01-01", "2023-12-31")


def _synthetic_fact(
    qname: str,
    value: float,
    start: str | None = None,
    end: str | None = None,
    instant: str | None = None,
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber(_SYNTHETIC_ACCESSION),
        concept_qname=qname,
        value=value,
        unit="USD",
        period_type="instant" if instant is not None else "duration",
        start_date=start,
        end_date=end,
        instant_date=instant,
    )


def _create_synthetic_xbrl(facts: tuple[XbrlFact, ...]) -> Xbrl:
    bundle = FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(),
    )
    return Xbrl(bundle, load_domain_taxonomy())


_TIMING_AXIS = (
    "us-gaap:RevenueRemainingPerformanceObligation"
    "ExpectedTimingOfSatisfactionStartDateAxis"
)
_RPO_CONCEPT = "us-gaap:RevenueRemainingPerformanceObligation"


def _timed_rpo(value: float, member: str) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber(_SYNTHETIC_ACCESSION),
        concept_qname=_RPO_CONCEPT,
        value=value,
        unit="USD",
        period_type="instant",
        instant_date="2023-12-31",
        dimensions={_TIMING_AXIS: member},
    )


def _canned_result(status: QueryStatus, scope: FactScope) -> FinancialQueryResult:
    return FinancialQueryResult(FinancialQuery("term", scope), status)


def _sub_root(graph: StatementGraph | None) -> str | None:
    """Root qname of a sub-graph, None when the sub-graph is absent."""
    if graph is None or graph.root is None:
        return None
    return graph.root.concept_qname
