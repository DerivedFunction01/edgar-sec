"""Level 3 rollforward specimens from the statement battery."""

from __future__ import annotations

from tests.apps.client.xbrl.battery.statement_battery_support import _battery, _facade


def test_level3_rollforward_reproduces_met_transfers_specimen() -> None:
    """MET corporate debt rollforward verifies, transfers-in tied to battery."""
    entry = _battery("met-level3-transfers-in")
    axis, member = entry.dimensions[0]
    view = _facade(entry.accession).financials.level3_rollforward(
        axis_qname=axis, member_qname=member
    )
    assert view.transfers_in == entry.expected_value
    assert view.opening == 28_345_000_000.0
    assert view.closing == 26_505_000_000.0
    assert view.gains_earnings == -143_000_000.0
    assert view.gains_oci == -1_177_000_000.0
    assert view.purchases == 5_587_000_000.0
    assert view.sales == 2_236_000_000.0
    assert view.transfers_out == 4_103_000_000.0
    assert view.verified is True
    assert view.discrepancy == 0.0
    assert view.missing_components == ()


def test_level3_rollforward_verifies_met_derivative_class() -> None:
    """MET net-derivative rollforward verifies from a negative opening."""
    view = _facade("0001099219-25-000044").financials.level3_rollforward(
        axis_qname="us-gaap:DerivativeInstrumentRiskAxis",
        member_qname="met:NetDerivativesMember",
    )
    assert view.opening == -143_000_000.0
    assert view.closing == 5_000_000.0
    assert view.verified is True
    assert view.discrepancy == 0.0


def test_level3_rollforward_verifies_bac_asset_and_liability_classes() -> None:
    """BAC asset and liability classes verify; liability gains flip sign."""
    accession = _battery("bac-2024-cash-rollup").accession
    asset = _facade(accession).financials.level3_rollforward(
        axis_qname="us-gaap:FairValueByAssetClassAxis",
        member_qname="us-gaap:DebtSecuritiesMember",
    )
    assert asset.opening == 376_000_000.0
    assert asset.closing == 611_000_000.0
    assert asset.verified is True
    liability = _facade(accession).financials.level3_rollforward(
        axis_qname="us-gaap:FairValueByLiabilityClassAxis",
        member_qname="us-gaap:LongTermDebtMember",
    )
    assert liability.opening == 614_000_000.0
    assert liability.closing == 553_000_000.0
    assert liability.gains_earnings == 64_000_000.0
    assert liability.verified is True
    assert liability.graph.side == "liability"


def test_level3_rollforward_verifies_jpm_loans_by_components_and_change() -> None:
    """JPM loans verify by components and by the filed period net change."""
    view = _facade("0000019617-25-000270").financials.level3_rollforward(
        axis_qname="us-gaap:FairValueByAssetClassAxis",
        member_qname="jpm:LoansReceivableNotForTradingMember",
    )
    assert view.opening == 3_079_000_000.0
    assert view.closing == 2_416_000_000.0
    assert view.verified is True
    assert view.net_change == -663_000_000.0
    assert view.change_verified is True
    assert view.missing_components == ("issues",)


def test_level3_rollforward_reports_ms_gap_with_missing_component() -> None:
    """MS commodity derivatives fall short; the gap and missing role show."""
    view = _facade("0000895421-25-000304").financials.level3_rollforward(
        axis_qname="us-gaap:DerivativeInstrumentRiskAxis",
        member_qname="ms:CommodityAndOtherContractsMember",
    )
    assert view.opening == 1_290_000_000.0
    assert view.closing == 1_308_000_000.0
    assert view.verified is False
    assert view.discrepancy == -306_000_000.0
    assert "sales" in view.missing_components
