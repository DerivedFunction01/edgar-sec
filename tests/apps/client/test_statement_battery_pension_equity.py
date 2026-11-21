"""Pension funded status and equity rollforward specimens."""

from __future__ import annotations

from tests.apps.client.statement_battery_support import (
    _AOCI_MEMBER,
    _EQ_AXIS,
    _LOCATION_AXIS,
    _RE_MEMBER,
    _TYPE_AXIS,
    _battery,
    _facade,
)


def test_pension_funded_status_verifies_ford_us_pension_class() -> None:
    """Ford US pension: both rollforwards and funded status verify."""
    view = _facade("0000037996-25-000013").financials.pension_funded_status(
        axis_qname=_LOCATION_AXIS, member_qname="country:US"
    )
    assert view.assets_opening == 31_423_000_000.0
    assert view.assets_closing == 29_502_000_000.0
    assert view.plan_assets.movements["actual_return"] == 13_000_000.0
    assert view.plan_assets.movements["employer_contributions"] == 808_000_000.0
    assert view.plan_assets.movements["benefits_paid"] == 2_706_000_000.0
    assert view.assets_verified is True
    assert view.obligation_opening == 32_676_000_000.0
    assert view.obligation_closing == 30_555_000_000.0
    assert view.obligation.movements["service_cost"] == 288_000_000.0
    assert view.obligation.movements["actuarial"] == 1_359_000_000.0
    assert view.obligation_verified is True
    assert view.funded_status == -1_053_000_000.0
    assert view.funded_status_filed == -1_053_000_000.0
    assert view.funded_verified is True
    assert view.missing_components == ()


def test_pension_funded_status_verifies_ford_foreign_and_opeb_classes() -> None:
    """Ford foreign pension and OPEB classes verify on all three checks."""
    foreign = _facade("0000037996-25-000013").financials.pension_funded_status(
        axis_qname=_LOCATION_AXIS, member_qname="us-gaap:ForeignPlanMember"
    )
    assert foreign.assets_opening == 22_958_000_000.0
    assert foreign.assets_closing == 21_751_000_000.0
    assert foreign.assets_verified is True
    assert foreign.obligation_opening == 24_004_000_000.0
    assert foreign.obligation_closing == 21_245_000_000.0
    assert foreign.obligation_verified is True
    assert foreign.funded_status == 506_000_000.0
    assert foreign.funded_verified is True
    opeb = _facade("0000037996-25-000013").financials.pension_funded_status(
        axis_qname=_TYPE_AXIS,
        member_qname="us-gaap:OtherPostretirementBenefitPlansDefinedBenefitMember",
    )
    assert opeb.assets_closing == 0.0
    assert opeb.obligation_opening == 4_696_000_000.0
    assert opeb.obligation_closing == 4_415_000_000.0
    assert opeb.obligation_verified is True
    assert opeb.funded_status == -4_415_000_000.0
    assert opeb.funded_verified is True


def test_equity_rollforward_verifies_aapl_statement() -> None:
    """AAPL equity statement verifies per component and in total."""
    entry = _battery("aapl-segment-revenue-china")
    view = _facade(entry.accession).statements.equity_rollforward()
    assert view.axis_qname == _EQ_AXIS
    assert view.balance_concept == "us-gaap:StockholdersEquity"
    assert view.opening == 62_146_000_000.0
    assert view.closing == 56_950_000_000.0
    assert view.verified is True
    assert view.discrepancy == 0.0
    assert view.components_verified is True
    common = view.component("us-gaap:CommonStockIncludingAdditionalPaidInCapitalMember")
    assert common is not None
    assert common.opening == 73_812_000_000.0
    assert common.closing == 83_276_000_000.0
    assert common.movements["share_based_compensation"] == 12_034_000_000.0
    assert common.movements["issuance"] == 1_423_000_000.0
    assert common.movements["tax_withholding"] == -3_993_000_000.0
    assert common.verified is True
    retained = view.component(_RE_MEMBER)
    assert retained is not None
    assert retained.opening == -214_000_000.0
    assert retained.closing == -19_154_000_000.0
    assert retained.movements["net_income"] == 93_736_000_000.0
    assert retained.movements["dividends"] == -15_218_000_000.0
    assert retained.movements["repurchase"] == -95_846_000_000.0
    assert retained.verified is True
    aoci = view.component(_AOCI_MEMBER)
    assert aoci is not None
    assert aoci.opening == -11_452_000_000.0
    assert aoci.closing == -7_172_000_000.0
    assert aoci.movements["oci"] == 4_280_000_000.0
    assert aoci.verified is True
    assert set(view.antichain_members) == {
        "us-gaap:CommonStockIncludingAdditionalPaidInCapitalMember",
        _RE_MEMBER,
        _AOCI_MEMBER,
    }
    assert view.missing_components == ()


def test_equity_rollforward_verifies_msft_components_reports_common_gap() -> None:
    """MSFT retained earnings and AOCI verify; the common gap is reported."""
    view = _facade("0000950170-24-087843").statements.equity_rollforward()
    assert view.opening == 206_223_000_000.0
    assert view.closing == 268_477_000_000.0
    assert view.components_verified is True
    retained = view.component(_RE_MEMBER)
    assert retained is not None
    assert retained.opening == 118_848_000_000.0
    assert retained.closing == 173_144_000_000.0
    assert retained.movements["net_income"] == 88_136_000_000.0
    assert retained.movements["dividends"] == -22_293_000_000.0
    assert retained.movements["repurchase"] == -11_547_000_000.0
    assert retained.verified is True
    aoci = view.component(_AOCI_MEMBER)
    assert aoci is not None
    assert aoci.opening == -6_343_000_000.0
    assert aoci.closing == -5_590_000_000.0
    assert aoci.movements["oci"] == 753_000_000.0
    assert aoci.verified is True
    common = view.component("us-gaap:CommonStockIncludingAdditionalPaidInCapitalMember")
    assert common is not None
    assert common.verified is False
    assert common.discrepancy == 362_000_000.0
    assert view.verified is False
    assert view.discrepancy == 362_000_000.0


def test_equity_rollforward_verifies_jpm_components() -> None:
    """JPM APIC, preferred, treasury, and AOCI verify; retained gap shows."""
    view = _facade("0000019617-25-000270").statements.equity_rollforward()
    assert view.opening == 327_878_000_000.0
    assert view.closing == 344_758_000_000.0
    assert view.components_verified is True
    apic = view.component("us-gaap:AdditionalPaidInCapitalMember")
    assert apic is not None
    assert apic.opening == 90_128_000_000.0
    assert apic.closing == 90_911_000_000.0
    assert apic.movements["share_based_compensation"] == 768_000_000.0
    assert apic.movements["other"] == 15_000_000.0
    assert apic.verified is True
    preferred = view.component(
        "us-gaap:PreferredStockIncludingAdditionalPaidInCapitalMember"
    )
    assert preferred is not None
    assert preferred.opening == 27_404_000_000.0
    assert preferred.closing == 20_050_000_000.0
    assert preferred.movements["issuance"] == 2_496_000_000.0
    assert preferred.movements["repurchase"] == -9_850_000_000.0
    assert preferred.verified is True
    treasury = view.component("us-gaap:TreasuryStockCommonMember")
    assert treasury is not None
    assert treasury.opening == -116_217_000_000.0
    assert treasury.closing == -134_018_000_000.0
    assert treasury.movements["treasury_acquired"] == -19_007_000_000.0
    assert treasury.movements["treasury_reissued"] == 1_206_000_000.0
    assert treasury.verified is True
    common = view.component("us-gaap:CommonStockMember")
    assert common is not None
    assert common.movements == {}
    assert common.verified is True
    aoci = view.component(_AOCI_MEMBER)
    assert aoci is not None
    assert aoci.opening == -10_443_000_000.0
    assert aoci.closing == -12_456_000_000.0
    assert aoci.movements["oci"] == -2_013_000_000.0
    assert aoci.verified is True
    retained = view.component(_RE_MEMBER)
    assert retained is not None
    assert retained.verified is False
    assert retained.discrepancy == -161_000_000.0
    assert view.verified is False
    assert view.discrepancy == -161_000_000.0


def test_equity_rollforward_serves_cat_including_nci_total() -> None:
    """CAT's balance concept is the including-noncontrolling-interest total."""
    view = _facade("0000018230-25-000008").statements.equity_rollforward()
    assert (
        view.balance_concept
        == "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    )
    assert view.opening == 19_503_000_000.0
    assert view.closing == 19_494_000_000.0
    assert view.components_verified is True
    retained = view.component(_RE_MEMBER)
    assert retained is not None
    assert retained.opening == 51_250_000_000.0
    assert retained.closing == 59_352_000_000.0
    assert retained.movements["net_income"] == 10_792_000_000.0
    assert retained.movements["dividends"] == -2_690_000_000.0
    assert retained.verified is True
    aoci = view.component(_AOCI_MEMBER)
    assert aoci is not None
    assert aoci.verified is False
    assert aoci.discrepancy == -24_000_000.0
    assert view.verified is False
    assert view.discrepancy == -28_000_000.0
    via_financials = _facade("0000018230-25-000008").financials.equity_rollforward()
    assert via_financials.closing == view.closing


def test_pension_funded_status_verifies_cat_us_pension_class() -> None:
    """CAT US pension verifies; its frozen plan files zero service cost."""
    view = _facade("0000018230-25-000008").financials.pension_funded_status(
        axis_qname=_LOCATION_AXIS, member_qname="country:US"
    )
    assert view.assets_opening == 12_738_000_000.0
    assert view.assets_closing == 11_898_000_000.0
    assert view.assets_verified is True
    assert view.obligation_opening == 13_137_000_000.0
    assert view.obligation_closing == 12_171_000_000.0
    assert view.obligation.movements["service_cost"] == 0.0
    assert view.obligation.movements["interest_cost"] == 625_000_000.0
    assert view.obligation_verified is True
    assert view.funded_status == -273_000_000.0
    assert view.funded_status_filed == -273_000_000.0
    assert view.funded_verified is True
