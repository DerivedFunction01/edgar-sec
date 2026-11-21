"""Financials core: the served machinery beneath the metric catalogue."""

from __future__ import annotations

import pytest

from edgar_sec.apps.client.composition import CompositionResult, OperandResolution
from edgar_sec.apps.client.facts import DisplayRecord
from edgar_sec.apps.client.financials import XbrlFinancials
from edgar_sec.apps.client.financials_core import FinancialsCore
from edgar_sec.apps.client.kernel import FilingKernel
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery.cohort import (
    canonical_seed_cohort_path,
    canonical_vintage_cohort_path,
)
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import load_filing, registry_filings
from tests.support import bundle_dir


def _msft() -> Xbrl:
    return Xbrl.from_bundle(bundle_dir("msft_2024_10k"), load_domain_taxonomy())


_COHORT_FACADES: dict[str, Xbrl] = {}


def _registry_facade(accession, registry_path) -> Xbrl:
    if accession not in _COHORT_FACADES:
        seed = next(
            s
            for s in registry_filings(registry_path=registry_path)
            if str(s.accession) == accession
        )
        loaded = load_filing(seed, registry_path=registry_path)
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
        _COHORT_FACADES[accession] = Xbrl(bundle, load_domain_taxonomy())
    return _COHORT_FACADES[accession]


def _duration_fact(qname: str, value: float) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any("0000000000-24-000000"),
        concept_qname=qname,
        value=value,
        unit="USD",
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
    )


def _synthetic_financials(facts, arcs) -> XbrlFinancials:
    bundle = FilingXbrl(
        accession=AccessionNumber.from_any("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs),
    )
    return Xbrl(bundle, load_domain_taxonomy()).financials


def _stripped_financials(
    facade: Xbrl, *drops: str, drop_income: bool = False
) -> XbrlFinancials:
    kernel = facade.financials._kernel

    def keep(fact: XbrlFact) -> bool:
        if any(drop in fact.concept_qname for drop in drops):
            return False
        if drop_income:
            atom = kernel.atom(fact.concept_qname)
            if atom is not None and atom.head == "H_INCOME":
                return False
        return True

    bare = FilingKernel(
        tuple(f for f in kernel.facts if keep(f)),
        kernel.calculation_arcs,
        kernel.taxonomy,
        labels=kernel.labels,
        records=kernel.records,
        declarations=kernel.declarations,
    )
    return XbrlFinancials(bare)


def test_core_machinery_serves_through_the_catalogue() -> None:
    """The extracted core serves the catalogue's metrics unchanged."""
    facade = Xbrl.from_bundle(bundle_dir("msft_2024_10k"), load_domain_taxonomy())
    fin = facade.financials
    assert isinstance(fin, FinancialsCore)
    served, served_class = fin._series_served("H_REVENUE")
    assert served_class == "ANNUAL"
    assert served == fin.revenue_series
    assert served["2024"] == 245_122_000_000.0


def test_eps_filed_posture_on_seed_specimen() -> None:
    """Filed EPS serves as filed, with filed provenance and a full series."""
    fin = _msft().financials
    assert fin.eps_basic == 11.86
    assert fin.eps_diluted == 11.80
    assert fin.provenance("eps_basic") == "filed"
    assert fin.provenance("eps_diluted") == "filed"
    assert fin.span_class("eps_basic") == "ANNUAL"
    assert fin.eps_basic_series == {"2022": 9.70, "2023": 9.72, "2024": 11.86}
    assert fin.eps_diluted_series == {"2022": 9.65, "2023": 9.68, "2024": 11.80}
    delta, pct = fin.eps_basic_yoy
    assert delta == pytest.approx(2.14)
    assert pct == pytest.approx(2.14 / 9.72)


def test_eps_filed_value_is_not_displaced_by_the_quotient() -> None:
    """The filed 11.86 stands even though the identity quotient is 11.8606."""
    filed = _msft().financials
    derived = _stripped_financials(_msft(), "EarningsPerShare")
    assert derived.eps_basic == 11.8606
    assert filed.eps_basic == 11.86
    assert filed.eps_basic != derived.eps_basic


def test_eps_derived_posture_when_eps_is_unfiled() -> None:
    """Both legs filed and EPS unfiled: derived, naming identity and legs."""
    fin = _stripped_financials(_msft(), "EarningsPerShare")
    assert fin.eps_basic == 11.8606
    assert fin.eps_diluted == 11.8002
    provenance = fin.provenance("eps_basic")
    assert provenance is not None
    assert provenance.startswith("DERIVED_EXACT:ACCOUNTING_IDENTITY:ID_EPS_BASIC")
    assert "us-gaap:NetIncomeLoss(88136000000.0)" in provenance
    assert "WeightedAverageNumberOfSharesOutstandingBasic(7431000000.0)" in provenance
    assert fin.eps_basic_series == {"2022": 9.7036, "2023": 9.7181, "2024": 11.8606}


def test_eps_missing_leg_serves_not_available() -> None:
    """EPS unfiled and a leg missing: honestly unserved, no substitution."""
    no_shares = _stripped_financials(
        _msft(), "EarningsPerShare", "WeightedAverageNumberOf"
    )
    assert no_shares.eps_basic is None
    assert no_shares.provenance("eps_basic") is None
    no_numerator = _stripped_financials(_msft(), "EarningsPerShare", drop_income=True)
    assert no_numerator.eps_basic is None
    assert no_numerator.eps_basic_series == {}


def test_weighted_shares_serve_filed_counts() -> None:
    """Share counts serve as filed, in scalar, series, and yoy shapes."""
    fin = _msft().financials
    assert fin.weighted_shares_basic == 7_431_000_000.0
    assert fin.weighted_shares_diluted == 7_469_000_000.0
    assert fin.weighted_shares_basic_series == {
        "2022": 7_496_000_000.0,
        "2023": 7_446_000_000.0,
        "2024": 7_431_000_000.0,
    }
    assert fin.provenance("weighted_shares_basic") == "filed"
    assert fin.span_class("weighted_shares_diluted") == "ANNUAL"
    delta, pct = fin.weighted_shares_basic_yoy
    assert delta == -15_000_000.0
    assert pct == pytest.approx(-15_000_000.0 / 7_446_000_000.0)


def test_per_share_metrics_wire_into_value_and_span_class() -> None:
    """value() reaches the new series; the bare eps name stays unserved."""
    fin = _msft().financials
    assert fin.value("eps_basic") == 11.86
    assert fin.value("eps_basic", period_offset=1) == 9.72
    assert fin.value("weighted_shares_diluted") == 7_469_000_000.0
    with pytest.raises(ValueError, match="unknown metric"):
        fin.value("eps")
    with pytest.raises(ValueError, match="not tracked"):
        fin.provenance("revenue")


_BAC_2013 = "0000070858-14-000012"
_BAC_2024 = "0000070858-25-000139"
_PURCHASE_PPE_QNAME = (
    "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
)
_SALE_MARKED_PURCHASE_QNAME = (
    "acme:PurchaseAndSaleOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
)


def _fact_at(qname: str, value: float, start: str, end: str) -> XbrlFact:
    """One undimensioned duration fact over an explicit span."""
    return XbrlFact(
        accession=AccessionNumber.from_any("0000000000-24-000000"),
        concept_qname=qname,
        value=value,
        unit="USD",
        period_type="duration",
        start_date=start,
        end_date=end,
    )


def test_capex_payments_coordinate_governs_shared_years() -> None:
    """Both dialects filed: payments govern shared years, purchase fills."""
    facts = (
        _fact_at(
            "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
            300.0,
            "2023-01-01",
            "2023-12-31",
        ),
        _fact_at(_PURCHASE_PPE_QNAME, 500.0, "2023-01-01", "2023-12-31"),
        _fact_at(_PURCHASE_PPE_QNAME, 700.0, "2024-01-01", "2024-12-31"),
    )
    fin = _synthetic_financials(facts, ())
    assert fin.capex_series == {"2023": 300.0, "2024": 700.0}
    assert fin.capex == 700.0
    assert fin.series("capex", length_class="ANNUAL") == {
        "2023": 300.0,
        "2024": 700.0,
    }
    assert fin.span_class("capex") == "ANNUAL"


def test_capex_excludes_a_sale_marked_purchase_line() -> None:
    """The sale exclusion keys on the marker at the purchase coordinate too."""
    facts = (_duration_fact(_SALE_MARKED_PURCHASE_QNAME, 100.0),)
    fin = _synthetic_financials(facts, ())
    assert fin.capex is None
    assert fin.capex_series == {}


_COMBINED_PURCHASE_QNAME = (
    "ifrs-full:PurchaseOfPropertyPlantAndEquipmentIntangibleAssets"
    "OtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets"
)
_BARE_PURCHASE_QNAME = "acme:PurchaseOfPropertyPlantAndEquipment"
_DISPOSAL_PROCEEDS_QNAME = (
    "ifrs-full:ProceedsFromDisposalsOfPropertyPlantAndEquipment"
    "IntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets"
)


def test_capex_purchase_act_shape_serves_the_combined_line() -> None:
    """The combined unclassified purchase line serves (Barclays' shape)."""
    facts = (
        _fact_at(_COMBINED_PURCHASE_QNAME, 1_574_000_000.0, "2024-01-01", "2024-12-31"),
        _fact_at(_COMBINED_PURCHASE_QNAME, 1_859_000_000.0, "2025-01-01", "2025-12-31"),
    )
    fin = _synthetic_financials(facts, ())
    assert fin.capex_series == {"2024": 1_574_000_000.0, "2025": 1_859_000_000.0}
    assert fin.capex == 1_859_000_000.0


def test_capex_classified_shape_governs_the_purchase_act_shape() -> None:
    """Both purchase shapes filed: the classified shape governs its years."""
    facts = (
        _fact_at(_BARE_PURCHASE_QNAME, 900.0, "2023-01-01", "2023-12-31"),
        _fact_at(_PURCHASE_PPE_QNAME, 500.0, "2023-01-01", "2023-12-31"),
        _fact_at(_BARE_PURCHASE_QNAME, 700.0, "2024-01-01", "2024-12-31"),
    )
    fin = _synthetic_financials(facts, ())
    assert fin.capex_series == {"2023": 500.0, "2024": 700.0}
    assert fin.capex == 700.0


def test_capex_excludes_a_disposal_marked_proceeds_line() -> None:
    """A disposal-proceeds line is not capex; the purchase line serves."""
    facts = (
        _fact_at(_DISPOSAL_PROCEEDS_QNAME, 400_000.0, "2025-01-01", "2025-12-31"),
        _fact_at(_PURCHASE_PPE_QNAME, 485_210_000.0, "2025-01-01", "2025-12-31"),
    )
    fin = _synthetic_financials(facts, ())
    assert fin.capex == 485_210_000.0
    assert fin.capex_series == {"2025": 485_210_000.0}


def test_capex_disposal_proceeds_alone_serve_nothing() -> None:
    """A filing with only a disposal-proceeds line serves no capex."""
    facts = (_fact_at(_DISPOSAL_PROCEEDS_QNAME, 400_000.0, "2025-01-01", "2025-12-31"),)
    fin = _synthetic_financials(facts, ())
    assert fin.capex is None
    assert fin.capex_series == {}


def _leg_financials() -> XbrlFinancials:
    """Financials whose records carry both purchase-coordinate shapes."""
    atoms = {
        "acme:PurchaseOfPropertyPlantAndEquipment": Atom(
            "H_ASSET", frozenset({"M_PPE_CAPEX", "M_INVESTING", "M_PURCHASE"})
        ),
        "acme:PurchaseAndSaleOfPropertyPlantAndEquipment": Atom(
            "H_ASSET",
            frozenset({"M_PPE_CAPEX", "M_INVESTING", "M_PURCHASE", "M_SALE"}),
        ),
    }
    records = {
        qname: DisplayRecord(qname=qname, atom=atom, presumed_atom=atom)
        for qname, atom in atoms.items()
    }
    kernel = FilingKernel((), (), load_domain_taxonomy(), records=records)
    return XbrlFinancials(kernel)


def _capex_leg(qname: str, value: float) -> CompositionResult:
    """A composed chain whose capex leg resolved to one concept."""
    operand = OperandResolution(
        sign="-",
        term="capex",
        status=QueryStatus.REPORTED,
        value=value,
        concept_qname=qname,
    )
    return CompositionResult(
        status=QueryStatus.DERIVED, value=value, operands=(operand,)
    )


def test_chain_leg_refusal_covers_the_purchase_coordinate() -> None:
    """The capex-leg refusal keys on the leg atom's markers, not its head."""
    fin = _leg_financials()
    sale_leg = _capex_leg("acme:PurchaseAndSaleOfPropertyPlantAndEquipment", 10.0)
    clean_leg = _capex_leg("acme:PurchaseOfPropertyPlantAndEquipment", 10.0)
    zero_leg = _capex_leg("acme:PurchaseAndSaleOfPropertyPlantAndEquipment", 0.0)
    assert fin._chain_leg_refused(sale_leg)
    assert not fin._chain_leg_refused(clean_leg)
    assert not fin._chain_leg_refused(zero_leg)


def test_chain_leg_refusal_covers_a_disposal_marked_leg() -> None:
    """The widened exclusion refuses a disposal-marked chain capex leg."""
    qname = "acme:ProceedsFromDisposalOfPropertyPlantAndEquipment"
    atom = Atom("H_CASH", frozenset({"M_PPE_CAPEX", "M_DISPOSAL"}))
    records = {qname: DisplayRecord(qname=qname, atom=atom, presumed_atom=atom)}
    kernel = FilingKernel((), (), load_domain_taxonomy(), records=records)
    fin = XbrlFinancials(kernel)
    assert fin._chain_leg_refused(_capex_leg(qname, 10.0))
    assert not fin._chain_leg_refused(_capex_leg(qname, 0.0))


def test_revenue_parallel_extension_total_stands() -> None:
    """BAC's FTE total is no component of us-gaap:Revenues; it stands."""
    bac13 = _registry_facade(_BAC_2013, canonical_vintage_cohort_path()).financials
    assert bac13.revenue_series["2013"] == 89_801_000_000.0
    bac24 = _registry_facade(_BAC_2024, canonical_seed_cohort_path()).financials
    assert bac24.revenue_series["2024"] == 102_506_000_000.0


def test_revenue_component_shape_is_regime_independent() -> None:
    """A us-gaap filing with XP's calc shape serves the standard total."""
    facts = (
        _duration_fact("us-gaap:Revenues", 100.0),
        _duration_fact("acme:RevenueBeforeSalesTaxes", 130.0),
        _duration_fact("acme:SalesTaxesOnRevenue", 30.0),
    )
    arcs = (
        CalculationArc("us-gaap:Revenues", "acme:RevenueBeforeSalesTaxes", 1.0),
        CalculationArc("us-gaap:Revenues", "acme:SalesTaxesOnRevenue", -1.0),
    )
    fin = _synthetic_financials(facts, arcs)
    assert fin.revenue_series == {"2024": 100.0}
    assert fin.revenue == 100.0


def test_revenue_parallel_shape_keeps_the_extension_total() -> None:
    """With no calc relation, the larger extension total stands."""
    facts = (
        _duration_fact("us-gaap:Revenues", 100.0),
        _duration_fact("acme:RevenueBeforeSalesTaxes", 130.0),
        _duration_fact("acme:SalesTaxesOnRevenue", 30.0),
    )
    fin = _synthetic_financials(facts, ())
    assert fin.revenue_series == {"2024": 130.0}


def test_revenue_nearest_standard_ancestor_wins() -> None:
    """Two standard ancestors compete: the nearer in the calc tree serves."""
    facts = (
        _duration_fact("us-gaap:Revenues", 125.0),
        _duration_fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 110.0
        ),
        _duration_fact("acme:RevenueBeforeSalesTaxes", 130.0),
    )
    arcs = (
        CalculationArc(
            "us-gaap:Revenues",
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            1.0,
        ),
        CalculationArc(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "acme:RevenueBeforeSalesTaxes",
            1.0,
        ),
    )
    fin = _synthetic_financials(facts, arcs)
    assert fin.revenue_series == {"2024": 110.0}
