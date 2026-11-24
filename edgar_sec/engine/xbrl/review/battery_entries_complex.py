"""Complex-tier battery entries: dimensioned slices, fair-value and derivation checks."""

from __future__ import annotations

from edgar_sec.engine.xbrl.review.battery_entry import (
    BatteryEntry,
    COMPLEX,
    _AAPL,
    _AAPL_D,
    _BAC11,
    _BAC24,
    _CASH,
    _D24,
    _DUK,
    _FACTS,
    _MET,
    _MSFT,
    _MSFT_I,
    _REV,
    _e,
)

COMPLEX_SET: tuple[BatteryEntry, ...] = (
    # Complex tier — concept switch, dimensioned slices, fair-value and
    # adjustment-bearing concepts, a derivation-backed total.
    _e(
        "bac-2011-cash-predecessor",
        COMPLEX,
        "BAC",
        _BAC11,
        _CASH,
        120_102_000_000.0,
        instant="2011-12-31",
        verification="rendered text L7045 (WS1 specimen audit); also in RELATION_SET",
    ),
    _e(
        "bac-2024-cash-rollup",
        COMPLEX,
        "BAC",
        _BAC24,
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        290_114_000_000.0,
        instant="2024-12-31",
        verification="rendered text L4564 (WS1 register F); also in RELATION_SET",
    ),
    _e(
        "aapl-segment-revenue-china",
        COMPLEX,
        "AAPL",
        _AAPL,
        _REV,
        66_952_000_000.0,
        **_AAPL_D,
        dimensions=(
            ("us-gaap:StatementBusinessSegmentsAxis", "aapl:GreaterChinaSegmentMember"),
        ),
        verification="facts.parquet: dimensioned segment fact (StatementBusinessSegmentsAxis)",
    ),
    _e(
        "msft-cash-only-slice",
        COMPLEX,
        "MSFT",
        _MSFT,
        "us-gaap:Cash",
        11_571_000_000.0,
        **_MSFT_I,
        dimensions=(("us-gaap:FinancialInstrumentAxis", "us-gaap:CashMember"),),
        verification="facts.parquet: dimensioned fact (FinancialInstrumentAxis=CashMember); pair-set provenance, MSFT text L1661",
    ),
    _e(
        "met-level3-transfers-in",
        COMPLEX,
        "MET",
        _MET,
        "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisAssetTransfersIntoLevel3",
        232_000_000.0,
        **_D24,
        dimensions=(
            (
                "us-gaap:FairValueByAssetClassAxis",
                "us-gaap:CorporateDebtSecuritiesMember",
            ),
        ),
        verification="facts.parquet: dimensioned Level 3 reconciliation fact (FairValueByAssetClassAxis)",
    ),
    _e(
        "bac-xva-derivative-assets",
        COMPLEX,
        "BAC",
        _BAC24,
        "us-gaap:DerivativeCreditRiskValuationAdjustmentDerivativeAssets",
        328_000_000.0,
        instant="2024-12-31",
        verification=_FACTS + "; adjustment-bearing concept (ASC 820 XVA family)",
    ),
    _e(
        "duk-revenue-including-assessed-tax",
        COMPLEX,
        "DUK",
        _DUK,
        "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
        30_050_000_000.0,
        **_D24,
        verification="rendered text L6149 (WS4 pair-set provenance): excise taxes recognized on a gross basis",
    ),
    _e(
        "msft-liabilities-and-equity-verified",
        COMPLEX,
        "MSFT",
        _MSFT,
        "us-gaap:LiabilitiesAndStockholdersEquity",
        512_163_000_000.0,
        mode="VERIFY_DERIVATION",
        expected_status="VERIFIED",
        **_MSFT_I,
        verification=_FACTS
        + "; derivation check against the filing's calculation arcs",
    ),
)
