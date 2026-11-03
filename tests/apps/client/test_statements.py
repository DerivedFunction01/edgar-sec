"""Statement-factory specimen tests: plan factories on 11-K samples,
fund factories on N-CSR/N-CSRS samples and synthetic calc trees."""

from __future__ import annotations

from pathlib import Path

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
from tests.support import bundle_dir, fixture_path

_NET_ROOT = "us-gaap-ebp:EmployeeBenefitPlanNetAssetAvailableForBenefit"
_CHANGES_ROOT = (
    "us-gaap-ebp:EmployeeBenefitPlanChangeInNetAssetAvailableForBenefitIncreaseDecrease"
)

# folder -> (net values by year, changes values by year, net nodes, changes nodes)
_SAMPLE = {
    "msft_2025_11k": (
        {"2024": 65627337124.0, "2025": 77820483784.0},
        {"2025": 12193146660.0},
        12,
        10,
    ),
    "abt_2025_11k": (
        {"2024": 15725269000.0, "2025": 17841016000.0},
        {"2025": 2115747000.0},
        13,
        13,
    ),
    "r_2025_11k": (
        {"2023": 1945506000.0, "2024": 2325827000.0, "2025": 2656585000.0},
        {"2024": 291720000.0, "2025": 330758000.0},
        12,
        14,
    ),
    "key_2025_11k": (
        {"2023": 3726984216.0, "2024": 4129131619.0, "2025": 4677863774.0},
        {"2024": 402147403.0, "2025": 548732155.0},
        8,
        13,
    ),
    "duk_2025_11k": (
        {"2024": 11269744000.0, "2025": 12583488000.0},
        {"2025": 1313744000.0},
        8,
        13,
    ),
}

_FACADES: dict[str, Xbrl] = {}
_TAXONOMY = None


def _facade(folder: str) -> Xbrl:
    """One cached facade per probe bundle folder."""
    global _TAXONOMY
    if _TAXONOMY is None:
        _TAXONOMY = load_domain_taxonomy()
    if folder not in _FACADES:
        path = fixture_path(f"xbrl/probe/{folder}")
        _FACADES[folder] = Xbrl.from_bundle(Path(path), _TAXONOMY)
    return _FACADES[folder]


@pytest.mark.parametrize("folder", sorted(_SAMPLE))
def test_plan_factories_serve_sample(folder: str) -> None:
    """Both factories serve the filed roots, values, and face sizes."""
    net_values, changes_values, net_nodes, changes_nodes = _SAMPLE[folder]
    statements = _facade(folder).statements
    net = statements.plan_net_assets()
    changes = statements.plan_changes()
    assert net.status is QueryStatus.REPORTED
    assert changes.status is QueryStatus.REPORTED
    assert net.root is not None and net.root.concept_qname == _NET_ROOT
    assert changes.root is not None and changes.root.concept_qname == _CHANGES_ROOT
    assert net.root.values == net_values
    assert changes.root.values == changes_values
    assert len(net.nodes) == net_nodes
    assert len(changes.nodes) == changes_nodes


@pytest.mark.parametrize("folder", sorted(_SAMPLE))
def test_plan_reconciliation(folder: str) -> None:
    """Latest net delta equals the changes total, per filed totals."""
    statements = _facade(folder).statements
    net = statements.plan_net_assets()
    changes = statements.plan_changes()
    assert net.root is not None and changes.root is not None
    years = sorted(net.root.values)
    delta = net.root.values[years[-1]] - net.root.values[years[-2]]
    assert delta == changes.root.values[max(changes.root.values)]


@pytest.mark.parametrize(
    ("folder", "factory", "discrepancy"),
    [
        ("msft_2025_11k", "plan_changes", 6116277.0),
        ("r_2025_11k", "plan_net_assets", 1000.0),
    ],
)
def test_plan_antichain_filed_postures(
    folder: str, factory: str, discrepancy: float
) -> None:
    """Two graphs carry filed-data discrepancies, pinned as filed: an
    unarced decrease total, and rounding inside the filer's components."""
    view = getattr(_facade(folder).statements, factory)()
    outcome = view.verify_antichain()
    assert not outcome.is_valid
    assert outcome.discrepancy == discrepancy


@pytest.mark.parametrize(
    "folder", [f for f in sorted(_SAMPLE) if f not in ("msft_2025_11k", "r_2025_11k")]
)
def test_plan_antichain_valid(folder: str) -> None:
    """The remaining sample graphs verify exactly against filed totals."""
    statements = _facade(folder).statements
    assert statements.plan_net_assets().verify_antichain().is_valid
    assert statements.plan_changes().verify_antichain().is_valid


def test_plan_member_selection() -> None:
    """Default serves the largest plan; an explicit member serves its own."""
    statements = _facade("abt_2025_11k").statements
    default = statements.plan_net_assets()
    assert default.root is not None
    assert default.root.values["2025"] == 17841016000.0
    small = statements.plan_net_assets(member_qname="abt:EBP002Member")
    assert small.status is QueryStatus.REPORTED
    assert small.root is not None
    assert small.root.values == {"2024": 243299000.0, "2025": 271092000.0}
    small_changes = statements.plan_changes(member_qname="abt:EBP002Member")
    assert small_changes.root is not None
    assert small_changes.root.values == {"2025": 27793000.0}
    refused = statements.plan_net_assets(member_qname="abt:NopeMember")
    assert refused.status is QueryStatus.UNAVAILABLE


def test_plan_year_argument() -> None:
    """A year-scoped net-assets view serves that year's filed total."""
    view = _facade("msft_2025_11k").statements.plan_net_assets(year=2024)
    assert view.root is not None
    assert view.root.value == 65627337124.0


@pytest.mark.parametrize("folder", ["msft_2026_10q", "bsrr_2024_10k", "bsrr_2024_10ka"])
def test_plan_absence_on_probe_corporate_filings(folder: str) -> None:
    """Corporate probe filings serve the standard absence posture."""
    statements = _facade(folder).statements
    for view in (statements.plan_net_assets(), statements.plan_changes()):
        assert view.status is QueryStatus.UNAVAILABLE
        assert view.message == "No statement of this type is reported in this filing."


def test_plan_absence_on_seed_annual() -> None:
    """A seed-corpus corporate annual serves the absence posture."""
    facade = Xbrl.from_bundle(bundle_dir("msft_2024_10k"), load_domain_taxonomy())
    for view in (
        facade.statements.plan_net_assets(),
        facade.statements.plan_changes(),
    ):
        assert view.status is QueryStatus.UNAVAILABLE


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
