"""Financials core: the served machinery beneath the metric catalogue."""

from __future__ import annotations

import pytest

from edgar_sec.apps.client.financials import XbrlFinancials
from edgar_sec.apps.client.financials_core import FinancialsCore
from edgar_sec.apps.client.kernel import FilingKernel
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery.cohort import canonical_probe_cohort_path
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle, XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import load_filing, registry_filings
from tests.support import bundle_dir

_PROBE_FACADES: dict[str, Xbrl] = {}
_RECAST = "0001193125-26-436149"
_STARWOOD = "0000950170-25-095257"
_YYAI = "0001493152-26-017959"


def _msft() -> Xbrl:
    return Xbrl.from_bundle(bundle_dir("msft_2024_10k"), load_domain_taxonomy())


def _probe_facade(accession: str) -> Xbrl:
    if accession not in _PROBE_FACADES:
        seed = next(
            s
            for s in registry_filings(registry_path=canonical_probe_cohort_path())
            if str(s.accession) == accession
        )
        loaded = load_filing(seed, registry_path=canonical_probe_cohort_path())
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
        _PROBE_FACADES[accession] = Xbrl(bundle, load_domain_taxonomy())
    return _PROBE_FACADES[accession]


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


def test_eps_absent_on_probe_specimen_without_per_share_facts() -> None:
    """YYAI files no EPS and no complete legs: every per-share metric is None."""
    fin = _probe_facade(_YYAI).financials
    for metric in (
        "eps_basic",
        "eps_diluted",
        "weighted_shares_basic",
        "weighted_shares_diluted",
    ):
        assert getattr(fin, metric) is None
        assert getattr(fin, f"{metric}_series") == {}
        assert fin.provenance(metric) is None
        assert fin.span_class(metric) is None


def test_eps_filed_on_step6_specimens() -> None:
    """The recast and Starwood specimens serve their filed EPS as filed."""
    recast = _probe_facade(_RECAST).financials
    assert recast.eps_basic == 18.00
    assert recast.eps_diluted == 17.95
    assert recast.provenance("eps_basic") == "filed"
    starwood = _probe_facade(_STARWOOD).financials
    assert starwood.eps_basic == -1.68
    assert starwood.eps_diluted == -1.68
    assert starwood.eps_basic_series == {
        "2022": -0.14,
        "2023": -1.39,
        "2024": -1.68,
    }


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


_MSFT_10Q = "0001193125-26-436133"
_AAPL_Q3 = "0000320193-26-000020"
_CAT_Q2 = "0000018230-26-000046"
_TSN_10Q = "0000100493-24-000103"
_HOMETRUST_KT = "0001538263-24-000029"
_L3HARRIS_KT = "0000202058-20-000011"
_INSPIREMD_KT = "0001144204-12-050732"
_BSRR_10K = "0001558370-25-002056"
_C_10Q = "0000831001-23-000055"
_TCBX_S4 = "0001193125-22-161032"
_NTR_40F = "0001193125-24-055096"
_WHK_S1 = "0001193125-26-410790"


def test_classed_access_serves_interim_classes_exactly() -> None:
    """Quarterly and YTD classes both serve on 10-Q, at their own spans."""
    msft = _probe_facade(_MSFT_10Q).financials
    assert msft.filed_length_class() == "QUARTER"
    assert msft.value("revenue", length_class="QUARTER") == 92_279_000_000.0
    aapl = _probe_facade(_AAPL_Q3).financials
    assert aapl.value("revenue", length_class="YTD_3Q") == 364_357_000_000.0
    assert aapl.value("revenue", length_class="QUARTER") == 109_417_000_000.0
    assert aapl.span_class("revenue", length_class="QUARTER") == "QUARTER"
    cat = _probe_facade(_CAT_Q2).financials
    assert cat.value("revenue", length_class="YTD_2Q") == 37_958_000_000.0
    assert cat.value("revenue", length_class="QUARTER") == 20_543_000_000.0
    tsn = _probe_facade(_TSN_10Q).financials
    assert tsn.value("revenue", length_class="YTD_3Q") == 39_744_000_000.0


def test_classed_access_never_substitutes_another_class() -> None:
    """An unserved class answers empty/None, not the ladder's data."""
    aapl = _probe_facade(_AAPL_Q3).financials
    assert aapl.series("revenue", length_class="YTD_2Q") == {}
    assert aapl.value("revenue", length_class="YTD_2Q") is None
    assert aapl.span_class("revenue", length_class="YTD_2Q") is None
    assert aapl.series("revenue") == aapl.revenue_series
    assert aapl.value("revenue") == aapl.revenue


def test_transition_stub_and_annual_serve_side_by_side() -> None:
    """A 10-KT's stub class and annual class name different filed spans."""
    fin = _probe_facade(_HOMETRUST_KT).financials
    assert fin.transition_length_class() == "YTD_2Q"
    annual = fin.value("operating_cash_flow", length_class="ANNUAL")
    stub = fin.value("operating_cash_flow", length_class="YTD_2Q")
    assert annual == -42_396_000.0
    assert stub == -11_430_000.0


def test_capex_excludes_sale_proceeds() -> None:
    """Proceeds concepts never serve as capex; the payments concept does."""
    bsrr = _probe_facade(_BSRR_10K).financials
    assert bsrr.capex == 1_156_000.0
    hometrust = _probe_facade(_HOMETRUST_KT).financials
    assert hometrust.capex == 3_420_000.0


def test_free_cash_flow_is_the_served_operands_difference() -> None:
    """FCF equals served cfo minus served capex on the adjudicated filings."""
    bsrr = _probe_facade(_BSRR_10K).financials
    assert bsrr.free_cash_flow == 55_997_000.0
    assert bsrr.free_cash_flow == bsrr.operating_cash_flow - bsrr.capex
    ntr = _probe_facade(_NTR_40F).financials
    assert ntr.capex == 2_671_000_000.0
    assert ntr.free_cash_flow == 2_395_000_000.0
    assert ntr.free_cash_flow == ntr.operating_cash_flow - ntr.capex


def test_free_cash_flow_is_stub_coherent_on_transition_filings() -> None:
    """Transition FCF differences the stub year's own filed operands."""
    l3 = _probe_facade(_L3HARRIS_KT).financials
    assert l3.transition_length_class() == "YTD_2Q"
    assert l3.free_cash_flow == 766_000_000.0
    assert l3.value("free_cash_flow", length_class="YTD_2Q") == 766_000_000.0
    inspire = _probe_facade(_INSPIREMD_KT).financials
    assert inspire.free_cash_flow == -4_556_000.0


def test_capex_prefers_the_payments_line_over_an_aggregate() -> None:
    """C's payments-and-proceeds aggregate yields to the payments line."""
    fin = _probe_facade(_C_10Q).financials
    assert fin.capex == 1_634_000_000.0
    assert fin.free_cash_flow == -32_119_000_000.0
    series = fin.operating_cash_flow_series
    assert series[max(series)] == -30_485_000_000.0


def test_classed_free_cash_flow_is_exact_class_or_honest_none() -> None:
    """YYAI's annual difference serves at ANNUAL; the stub class refuses."""
    fin = _probe_facade(_YYAI).financials
    assert fin.free_cash_flow == 10_418_036.0
    assert fin.value("free_cash_flow", length_class="ANNUAL") == 10_418_036.0
    assert fin.value("free_cash_flow", length_class="YTD_3Q") is None
    assert fin.span_class("free_cash_flow", length_class="YTD_3Q") is None


def test_revenue_definition_exclusions() -> None:
    """Pro-forma revenue yields to the face total; accretion serves None."""
    whk = _probe_facade(_WHK_S1).financials
    assert whk.revenue == 67_595_000.0
    tcbx = _probe_facade(_TCBX_S4).financials
    assert tcbx.revenue is None
    assert tcbx.free_cash_flow == -1_442_000.0
