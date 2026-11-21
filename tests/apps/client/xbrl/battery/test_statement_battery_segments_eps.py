"""Segment breakdown and EPS specimens from the statement battery."""

from __future__ import annotations

from edgar_sec.engine.xbrl.review.battery import BATTERY_SET
from edgar_sec.engine.xbrl.solve.core.scoping import FactScope
from edgar_sec.engine.xbrl.solve.core.identities import verify_eps_identity

from tests.apps.client.xbrl.battery.statement_battery_support import (
    _EPS,
    _EPS_PINNED,
    _NODE_EXCLUDED_ENTRIES,
    _SERIES_PINNED,
    _battery,
    _facade,
    _loaded,
)


def test_segment_breakdown_reproduces_aapl_china_specimen() -> None:
    """AAPL business-segment revenue verifies, including the China member."""
    entry = _battery("aapl-segment-revenue-china")
    axis, member = entry.dimensions[0]
    view = _facade(entry.accession).financials.segment_breakdown(
        concept_qname=entry.qname, axis_qname=axis
    )
    assert view.total == _battery("aapl-revenue").expected_value
    assert view.values_by_member[member] == entry.expected_value
    assert len(view.members) == 5
    assert view.member_sum == view.total
    assert view.verified is True
    assert view.discrepancy == 0.0
    default = _facade(entry.accession).financials.segment_breakdown()
    assert default.concept_qname == entry.qname
    assert default.axis_qname == axis
    assert default.verified is True


def test_segment_breakdown_reproduces_msft_specimen() -> None:
    """MSFT business-segment revenue verifies across its three segments."""
    view = _facade("0000950170-24-087843").financials.segment_breakdown(
        concept_qname="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        axis_qname="us-gaap:StatementBusinessSegmentsAxis",
    )
    assert view.total == 245_122_000_000.0
    assert view.member_sum == view.total
    assert view.verified is True
    assert view.values_by_member == {
        "msft:ProductivityAndBusinessProcessesMember": 77_728_000_000.0,
        "msft:IntelligentCloudMember": 105_362_000_000.0,
        "msft:MorePersonalComputingMember": 62_032_000_000.0,
    }


def test_segment_breakdown_serves_msft_statement_declared_partition() -> None:
    """MSFT revenue's two filed partitions: the statement-declared pair serves."""
    view = _facade("0000950170-24-087843").financials.segment_breakdown(
        concept_qname="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        axis_qname="srt:ProductOrServiceAxis",
    )
    assert view.classification is not None
    assert view.classification.kind == "overlapping_partitions"
    assert view.total == 245_122_000_000.0
    assert view.member_sum == view.total
    assert view.verified is True
    assert view.values_by_member == {
        "us-gaap:ProductMember": 64_773_000_000.0,
        "us-gaap:ServiceOtherMember": 180_349_000_000.0,
    }
    assert view.filed_member_sum == 490_244_000_000.0
    assert len(view.alternates) == 1
    alternate = view.alternates[0]
    assert len(alternate) == 10
    assert sum(member.value for member in alternate) == 245_122_000_000.0
    # The bare call still resolves to NoncurrentAssets by geography: its
    # verified total (301,369,000,000) outranks every revenue candidate in
    # the bare-call ordering, before this plan and after it.
    default = _facade("0000950170-24-087843").financials.segment_breakdown()
    assert default.concept_qname == "us-gaap:NoncurrentAssets"
    assert default.axis_qname == "srt:StatementGeographicalAxis"
    assert default.verified is True


def test_segment_breakdown_reports_googl_gap() -> None:
    """GOOGL segment revenue falls short of the total; the gap is reported."""
    view = _facade("0001652044-25-000014").financials.segment_breakdown(
        concept_qname="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        axis_qname="us-gaap:StatementBusinessSegmentsAxis",
    )
    assert view.total == 350_018_000_000.0
    assert view.member_sum == 349_807_000_000.0
    assert view.verified is False
    assert view.discrepancy == 211_000_000.0


def test_eps_specimens_dispositioned_by_the_identity_route() -> None:
    """Every EPS specimen verifies by identity, or is pinned with evidence."""
    for entry in BATTERY_SET:
        if entry.qname not in _EPS:
            continue
        loaded = _loaded(entry.accession)
        scope = FactScope(
            accession=entry.accession, start_date=entry.start, end_date=entry.end
        )
        outcome = verify_eps_identity(
            loaded.facts, diluted=entry.qname.endswith("Diluted"), scope=scope
        )
        if entry.entry_id in _EPS_PINNED:
            assert outcome is None, entry.entry_id
            assert "pinned" in entry.verification, entry.entry_id
            filed = {fact.concept_qname for fact in loaded.facts}
            assert (
                "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding" not in filed
            )
            basic = {
                fact.value
                for fact in loaded.facts
                if fact.concept_qname == "us-gaap:EarningsPerShareBasic"
                and not fact.dimensions
                and fact.start_date == entry.start
                and fact.end_date == entry.end
            }
            assert basic == {entry.expected_value}, entry.entry_id
            continue
        assert outcome is not None, entry.entry_id
        assert outcome.passed, f"{entry.entry_id}: {outcome}"
        assert outcome.lhs_value == entry.expected_value, entry.entry_id
        assert outcome.tolerance == 0.005, entry.entry_id
        assert "EPS identity route" in entry.verification, entry.entry_id


def test_calc_isolated_node_pins_use_the_provenance_route() -> None:
    """Non-EPS calc-isolated pins carry facts.parquet provenance, not a calc route."""
    for entry_id in _NODE_EXCLUDED_ENTRIES:
        entry = _battery(entry_id)
        assert entry.verification.startswith("facts.parquet"), entry_id


def test_series_pins_headline_the_larger_filed_revenue_total() -> None:
    """Pinned series entries headline a larger filed revenue fact."""
    for entry in BATTERY_SET:
        if entry.entry_id not in _SERIES_PINNED:
            continue
        pinned = _SERIES_PINNED[entry.entry_id]
        assert pinned > entry.expected_value, entry.entry_id
        year = (entry.instant or entry.end)[:4]
        series = _facade(entry.accession).financials.revenue_series
        assert series.get(year) == pinned, entry.entry_id
        filed = {
            fact.value for fact in _loaded(entry.accession).facts if not fact.dimensions
        }
        assert pinned in filed, entry.entry_id
