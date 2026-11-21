"""Statement-factory tests: plan absence on a seed annual and
fund factories on synthetic calc trees."""

from __future__ import annotations


from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support.corpus import bundle_dir


def test_plan_absence_on_seed_annual() -> None:
    """A seed-corpus corporate annual serves the absence posture."""
    facade = Xbrl.from_bundle(bundle_dir("msft_2024_10k"), load_domain_taxonomy())
    for view in (
        facade.statements.plan_net_assets(),
        facade.statements.plan_changes(),
    ):
        assert view.status is QueryStatus.UNAVAILABLE


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
