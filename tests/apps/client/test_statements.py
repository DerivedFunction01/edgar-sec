"""Fund statement factories: honest posture on fund bundles, ties when filed."""

from __future__ import annotations

import pytest

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery.cohort import canonical_probe_cohort_path
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import load_filing, registry_filings

_FUND_ACCESSIONS = (
    "0001387131-23-003220",  # GDV, N-CSR, cef
    "0001829126-24-001446",  # GDL, N-CSR, cef
    "0001193125-24-213171",  # PTY, N-CSR, cef
    "0001100663-26-000065",  # iShares, N-CSR, oef
    "0001213900-23-084395",  # OXLC, N-CSRS, cef
    "0001193125-26-383427",  # TY, N-CSRS, cef
    "0001471420-25-000006",  # STK, N-CSRS, cef
    "0001100663-26-000049",  # iShares, N-CSRS, oef
)
_FUND_FACADES: dict[str, Xbrl] = {}


def _fund_facade(accession: str) -> Xbrl:
    if accession not in _FUND_FACADES:
        path = canonical_probe_cohort_path()
        seed = next(
            s
            for s in registry_filings(registry_path=path)
            if str(s.accession) == accession
        )
        loaded = load_filing(seed, registry_path=path)
        bundle = FilingXbrl(
            accession=AccessionNumber.from_any(accession),
            cik=Cik(int(seed.cik)),
            facts=loaded.facts,
            linkbases=LinkbaseBundle(
                calculation_arcs=loaded.calc_arcs,
                presentation_arcs=loaded.pres_arcs,
                declarations=tuple(loaded.declarations.values()),
            ),
        )
        _FUND_FACADES[accession] = Xbrl(bundle, load_domain_taxonomy())
    return _FUND_FACADES[accession]


@pytest.mark.parametrize("accession", _FUND_ACCESSIONS)
def test_fund_factories_serve_honest_absence_on_sample(accession: str) -> None:
    """Fund samples file no statement calc structure: both factories abstain."""
    statements = _fund_facade(accession).statements
    for factory in (statements.fund_assets_liabilities, statements.fund_operations):
        view = factory()
        assert view.status is QueryStatus.UNAVAILABLE
        assert view.nodes == {}
        assert view.message == "No statement of this type is reported in this filing."


_FUND_ACC = AccessionNumber("0000000000-25-000001")


def _fund_fact(qname: str, value: float, period_type: str, **dates: str) -> XbrlFact:
    return XbrlFact(
        accession=_FUND_ACC,
        concept_qname=qname,
        value=value,
        unit="USD",
        period_type=period_type,
        **dates,
    )


def _synthetic_fund() -> Xbrl:
    instant = {"instant_date": "2025-12-31"}
    duration = {"start_date": "2025-01-01", "end_date": "2025-12-31"}
    facts = (
        _fund_fact("us-gaap:AssetsNet", 750.0, "instant", **instant),
        _fund_fact("us-gaap:Assets", 1000.0, "instant", **instant),
        _fund_fact("us-gaap:Liabilities", 250.0, "instant", **instant),
        _fund_fact(
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            400.0,
            "instant",
            **instant,
        ),
        _fund_fact("us-gaap:ShortTermInvestments", 600.0, "instant", **instant),
        _fund_fact("us-gaap:NetIncomeLoss", 500.0, "duration", **duration),
        _fund_fact("us-gaap:Revenues", 800.0, "duration", **duration),
        _fund_fact("us-gaap:OperatingExpenses", 300.0, "duration", **duration),
    )
    dimensioned = XbrlFact(
        accession=_FUND_ACC,
        concept_qname="us-gaap:Assets",
        value=999999.0,
        unit="USD",
        period_type="instant",
        instant_date="2025-12-31",
        dimensions={"oef:ClassAxis": "xyz:SomeClassMember"},
    )
    arcs = (
        CalculationArc("us-gaap:AssetsNet", "us-gaap:Assets", 1.0),
        CalculationArc("us-gaap:AssetsNet", "us-gaap:Liabilities", -1.0),
        CalculationArc(
            "us-gaap:Assets",
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            1.0,
        ),
        CalculationArc("us-gaap:Assets", "us-gaap:ShortTermInvestments", 1.0),
        CalculationArc("us-gaap:NetIncomeLoss", "us-gaap:Revenues", 1.0),
        CalculationArc("us-gaap:NetIncomeLoss", "us-gaap:OperatingExpenses", -1.0),
    )
    bundle = FilingXbrl(
        accession=_FUND_ACC,
        cik=Cik(1),
        facts=facts + (dimensioned,),
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    return Xbrl(bundle, load_domain_taxonomy())


def test_fund_assets_liabilities_composes_and_reconciles() -> None:
    """A filed calc tree composes; assets − liabilities ties to net assets."""
    view = _synthetic_fund().statements.fund_assets_liabilities()
    assert view.status is QueryStatus.REPORTED
    assert view.root is not None
    assert view.root.concept_qname == "us-gaap:AssetsNet"
    assets = view.nodes["us-gaap:Assets"].value
    liabilities = view.nodes["us-gaap:Liabilities"].value
    net_assets = view.nodes["us-gaap:AssetsNet"].value
    assert assets is not None and liabilities is not None and net_assets is not None
    assert assets - liabilities == net_assets == 750.0


def test_fund_assets_liabilities_never_roots_a_fragment() -> None:
    """An H_ASSET concept below a non-asset root is not a fund statement."""
    facts = (
        _fund_fact("us-gaap:Assets", 1000.0, "instant", instant_date="2025-12-31"),
        _fund_fact(
            "us-gaap:OtherComprehensiveIncomeLossNetOfTax",
            1000.0,
            "duration",
            start_date="2025-01-01",
            end_date="2025-12-31",
        ),
    )
    arcs = (
        CalculationArc(
            "us-gaap:OtherComprehensiveIncomeLossNetOfTax", "us-gaap:Assets", 1.0
        ),
    )
    bundle = FilingXbrl(
        accession=_FUND_ACC,
        cik=Cik(1),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    view = Xbrl(bundle, load_domain_taxonomy()).statements.fund_assets_liabilities()
    assert view.status is QueryStatus.UNAVAILABLE
    assert view.nodes == {}


def test_fund_operations_composes_and_reconciles() -> None:
    """A filed duration tree composes; income − expenses ties to the bottom line."""
    view = _synthetic_fund().statements.fund_operations()
    assert view.status is QueryStatus.REPORTED
    assert view.root is not None
    assert view.root.concept_qname == "us-gaap:NetIncomeLoss"
    income = view.nodes["us-gaap:Revenues"].value
    expenses = view.nodes["us-gaap:OperatingExpenses"].value
    bottom = view.nodes["us-gaap:NetIncomeLoss"].value
    assert income is not None and expenses is not None and bottom is not None
    assert income - expenses == bottom == 500.0
