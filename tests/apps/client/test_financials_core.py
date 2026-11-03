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
