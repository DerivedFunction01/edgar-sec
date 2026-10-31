"""Unit tests for topic view builders over synthetic facts."""

from edgar_sec.apps.client.facts import build_display_records
from edgar_sec.apps.client.equity_rollforward import build_equity_rollforward
from edgar_sec.apps.client.rollforwards import (
    build_level3_rollforward,
    build_pension_funded_status,
)
from edgar_sec.apps.client.topics import (
    build_cash_rollforward,
    build_segment_breakdown,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import CalculationArc, DefinitionArc, XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy

_ACC = AccessionNumber("0000000000-25-000001")
_ROLLUP = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
_CHANGE_INC = (
    "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
    "PeriodIncreaseDecreaseIncludingExchangeRateEffect"
)
_CHANGE_EXC = (
    "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
    "PeriodIncreaseDecreaseExcludingExchangeRateEffect"
)
_FX = "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
_CARRYING = "us-gaap:CashAndCashEquivalentsAtCarryingValue"
_RESTRICTED = "us-gaap:RestrictedCash"


def _fact(qname: str, value: float, **kw: object) -> XbrlFact:
    return XbrlFact(_ACC, qname, value, unit="USD", **kw)  # type: ignore[arg-type]


def _instant(qname: str, value: float, day: str) -> XbrlFact:
    return _fact(qname, value, period_type="instant", instant_date=day)


def _duration(qname: str, value: float) -> XbrlFact:
    return _fact(
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
    )


def _build(facts: list[XbrlFact], arcs: tuple[CalculationArc, ...] = ()):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_cash_rollforward(facts, records, taxonomy, calculation_arcs=arcs)


def test_cash_rollforward_selects_identity_verified_total() -> None:
    """The compound total serves when beginning + change reproduces its end."""
    facts = [
        _instant(_ROLLUP, 1000.0, "2023-12-31"),
        _instant(_ROLLUP, 900.0, "2024-12-31"),
        _instant(_RESTRICTED, 80.0, "2023-12-31"),
        _instant(_RESTRICTED, 50.0, "2024-12-31"),
        _instant(_CARRYING, 850.0, "2024-12-31"),
        _duration(_CHANGE_INC, -100.0),
    ]
    graph = _build(facts)
    assert graph.total_concept == _ROLLUP
    assert graph.beginning == 1000.0
    assert graph.net_change == -100.0
    assert graph.end == 900.0
    assert graph.beginning_date == "2023-12-31"
    assert graph.end_date == "2024-12-31"
    assert graph.rollforward_verified is True
    assert graph.balance_sheet_total == 900.0
    assert graph.balance_sheet_verified is True


def test_cash_rollforward_calc_components_reconcile_end() -> None:
    """Calc children of the total reconcile it when they are filed lines."""
    facts = [
        _instant(_ROLLUP, 1000.0, "2023-12-31"),
        _instant(_ROLLUP, 900.0, "2024-12-31"),
        _instant("us-gaap:CashAndDueFromBanks", 300.0, "2024-12-31"),
        _instant("us-gaap:InterestBearingDepositsInBanks", 600.0, "2024-12-31"),
        _duration(_CHANGE_INC, -100.0),
    ]
    arcs = (
        CalculationArc(_ROLLUP, "us-gaap:CashAndDueFromBanks", 1.0),
        CalculationArc(_ROLLUP, "us-gaap:InterestBearingDepositsInBanks", 1.0),
    )
    graph = _build(facts, arcs)
    assert graph.balance_sheet_total == 900.0
    assert graph.balance_sheet_verified is True
    assert len(graph.components) == 2


def test_cash_rollforward_excluding_change_adds_fx_effect() -> None:
    """An excluding-FX change composes with the filed FX effect fact."""
    facts = [
        _instant(_ROLLUP, 1000.0, "2023-12-31"),
        _instant(_ROLLUP, 920.0, "2024-12-31"),
        _duration(_CHANGE_EXC, -100.0),
        _duration(_FX, 20.0),
    ]
    graph = _build(facts)
    assert graph.net_change == -80.0
    assert graph.rollforward_verified is True
    assert graph.balance_sheet_total is None
    assert graph.balance_sheet_verified is None


_REV = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
_BIZ_AXIS = "us-gaap:StatementBusinessSegmentsAxis"
_GEO_AXIS = "srt:StatementGeographicalAxis"


def _segment_fact(
    qname: str, value: float, dimensions: dict[str, str] | None = None, **kw: object
) -> XbrlFact:
    return _fact(
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        dimensions=dimensions or {},
        **kw,  # type: ignore[arg-type]
    )


def _build_segments(facts: list[XbrlFact], **kw: object):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_segment_breakdown(facts, records, taxonomy, **kw)  # type: ignore[arg-type]


def test_segment_breakdown_verifies_members_against_total() -> None:
    """Single-axis members summing to the total verify; other facts stay out."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}),
        _segment_fact(_REV, 400.0, {_BIZ_AXIS: "x:BetaMember"}),
        _segment_fact(_REV, 999.0, {_BIZ_AXIS: "x:AlphaMember", _GEO_AXIS: "x:US"}),
        _segment_fact(_REV, 700.0, {_GEO_AXIS: "x:US"}),
        _segment_fact(_REV, 300.0, {_GEO_AXIS: "x:NonUS"}),
    ]
    graph = _build_segments(facts, concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert graph.total == 1000.0
    assert graph.member_sum == 1000.0
    assert graph.verified is True
    assert graph.discrepancy == 0.0
    assert {m.member_qname: m.value for m in graph.members} == {
        "x:AlphaMember": 600.0,
        "x:BetaMember": 400.0,
    }
    default = _build_segments(facts)
    assert default.concept_qname == _REV
    assert default.axis_qname == _BIZ_AXIS
    assert default.verified is True


def test_segment_breakdown_reports_gap_without_forcing_balance() -> None:
    """Members short of the total serve with the discrepancy shown."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}),
        _segment_fact(_REV, 300.0, {_BIZ_AXIS: "x:BetaMember"}),
    ]
    graph = _build_segments(facts, concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert graph.member_sum == 900.0
    assert graph.verified is False
    assert graph.discrepancy == 100.0


def test_segment_breakdown_counts_each_member_once() -> None:
    """A repeated member fact is one antichain element, not a double count."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}, decimals=-6),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}, decimals=-3),
        _segment_fact(_REV, 400.0, {_BIZ_AXIS: "x:BetaMember"}),
    ]
    graph = _build_segments(facts, concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert len(graph.members) == 2
    assert graph.verified is True


def test_cash_rollforward_reports_unverified_gap() -> None:
    """A total whose identity fails is served with its discrepancy shown."""
    facts = [
        _instant(_ROLLUP, 1000.0, "2023-12-31"),
        _instant(_ROLLUP, 900.0, "2024-12-31"),
        _duration(_CHANGE_INC, -50.0),
    ]
    graph = _build(facts)
    assert graph.end == 900.0
    assert graph.rollforward_verified is False
    assert graph.rollforward_discrepancy == -50.0


_L3 = "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisAsset"
_L3_VALUE = _L3 + "Value"
_L3_AXIS = "us-gaap:FairValueByAssetClassAxis"
_L3_MEMBER = "x:CorpMember"


def _level3_fact(
    qname: str,
    value: float,
    dimensions: dict[str, str] | None = None,
    instant: str | None = None,
) -> XbrlFact:
    dims = {_L3_AXIS: _L3_MEMBER} if dimensions is None else dimensions
    if instant is not None:
        return _fact(
            qname, value, period_type="instant", instant_date=instant, dimensions=dims
        )
    return _fact(
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        dimensions=dims,
    )


def _build_level3(facts: list[XbrlFact], **kw: object):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_level3_rollforward(facts, records, taxonomy, **kw)  # type: ignore[arg-type]


def test_level3_rollforward_verifies_asset_class() -> None:
    """Opening plus signed components reproduces the closing balance."""
    facts = [
        _level3_fact(_L3_VALUE, 1000.0, instant="2023-12-31"),
        _level3_fact(_L3_VALUE, 850.0, instant="2024-12-31"),
        _level3_fact(_L3 + "GainLossIncludedInEarnings1", 100.0),
        _level3_fact(_L3 + "GainLossIncludedInOtherComprehensiveIncomeLoss", -50.0),
        _level3_fact(_L3 + "Purchases", 200.0),
        _level3_fact(_L3 + "Sales", 300.0),
        _level3_fact(_L3 + "Issues", 10.0),
        _level3_fact(_L3 + "Settlements", 20.0),
        _level3_fact(_L3 + "TransfersIntoLevel3", 30.0),
        _level3_fact(_L3 + "TransfersOutOfLevel3", 120.0),
    ]
    graph = _build_level3(facts, axis_qname=_L3_AXIS, member_qname=_L3_MEMBER)
    assert graph.opening == 1000.0
    assert graph.closing == 850.0
    assert graph.total_gains == 50.0
    assert graph.transfers_in == 30.0
    assert graph.verified is True
    assert graph.discrepancy == 0.0
    assert graph.missing_components == ()
    assert graph.side == "asset"


_L3L = "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisLiability"
_L3L_VALUE = (
    "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliations"
    "RecurringBasisLiabilityValue"
)
_L3L_AXIS = "us-gaap:FairValueByLiabilityClassAxis"


def test_level3_rollforward_flips_gains_for_liability_class() -> None:
    """A filed liability loss increases the balance; the sign flips."""
    dims = {_L3L_AXIS: "x:DebtMember"}
    facts = [
        _level3_fact(_L3L_VALUE, 1000.0, dims, instant="2023-12-31"),
        _level3_fact(_L3L_VALUE, 1000.0, dims, instant="2024-12-31"),
        _level3_fact(_L3L + "GainLossIncludedInEarnings", -200.0, dims),
        _level3_fact(_L3L + "Issues", 100.0, dims),
        _level3_fact(_L3L + "Settlements", 300.0, dims),
    ]
    graph = _build_level3(facts, axis_qname=_L3L_AXIS, member_qname="x:DebtMember")
    assert graph.side == "liability"
    assert graph.verified is True
    assert graph.discrepancy == 0.0


def test_level3_rollforward_reports_gap_and_missing_components() -> None:
    """An unreconciled closing serves with its gap and missing roles named."""
    facts = [
        _level3_fact(_L3_VALUE, 1000.0, instant="2023-12-31"),
        _level3_fact(_L3_VALUE, 900.0, instant="2024-12-31"),
        _level3_fact(_L3 + "Purchases", 200.0),
    ]
    graph = _build_level3(facts, axis_qname=_L3_AXIS, member_qname=_L3_MEMBER)
    assert graph.verified is False
    assert graph.discrepancy == -300.0
    assert "gains" in graph.missing_components
    assert "sales" in graph.missing_components
    assert "transfers" in graph.missing_components


def test_level3_rollforward_counts_net_transfers_as_filed() -> None:
    """A single net transfers fact satisfies the transfers component."""
    facts = [
        _level3_fact(_L3_VALUE, 1000.0, instant="2023-12-31"),
        _level3_fact(_L3_VALUE, 1050.0, instant="2024-12-31"),
        _level3_fact(_L3 + "Purchases", 100.0),
        _level3_fact(_L3 + "TransfersNet", -50.0),
    ]
    graph = _build_level3(facts, axis_qname=_L3_AXIS, member_qname=_L3_MEMBER)
    assert graph.transfers_net == -50.0
    assert graph.verified is True
    assert "transfers" not in graph.missing_components


_PENSION_AXIS = "us-gaap:RetirementPlanTypeAxis"
_PENSION_MEMBER = "us-gaap:PensionPlansDefinedBenefitMember"
_PENSION_DIMS = {_PENSION_AXIS: _PENSION_MEMBER}
_DB = "us-gaap:DefinedBenefitPlan"


def _pension_fact(qname: str, value: float, instant: str | None = None) -> XbrlFact:
    if instant is not None:
        return _fact(
            qname,
            value,
            period_type="instant",
            instant_date=instant,
            dimensions=_PENSION_DIMS,
        )
    return _fact(
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        dimensions=_PENSION_DIMS,
    )


def _build_pension(facts: list[XbrlFact], **kw: object):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_pension_funded_status(facts, records, taxonomy, **kw)  # type: ignore[arg-type]


def _pension_facts(closing_assets: float = 1000.0) -> list[XbrlFact]:
    return [
        _pension_fact(_DB + "FairValueOfPlanAssets", 1000.0, instant="2023-12-31"),
        _pension_fact(
            _DB + "FairValueOfPlanAssets", closing_assets, instant="2024-12-31"
        ),
        _pension_fact(_DB + "BenefitObligation", 1200.0, instant="2023-12-31"),
        _pension_fact(_DB + "BenefitObligation", 1225.0, instant="2024-12-31"),
        _pension_fact(_DB + "FundedStatusOfPlan", -225.0, instant="2024-12-31"),
        _pension_fact(_DB + "ActualReturnOnPlanAssets", 100.0),
        _pension_fact(_DB + "ContributionsByEmployer", 200.0),
        _pension_fact(_DB + "PlanAssetsContributionsByPlanParticipant", 10.0),
        _pension_fact(_DB + "PlanAssetsBenefitsPaid", 300.0),
        _pension_fact(_DB + "SettlementsPlanAssets", 20.0),
        _pension_fact(_DB + "PlanAssetsForeignCurrencyTranslationGainLoss", -30.0),
        _pension_fact("x:DefinedBenefitPlanOtherIncreaseDecreasePlanAssets", 40.0),
        _pension_fact(_DB + "ServiceCost", 150.0),
        _pension_fact(_DB + "InterestCost", 250.0),
        _pension_fact(_DB + "BenefitObligationContributionsByPlanParticipant", 10.0),
        _pension_fact(_DB + "BenefitObligationBenefitsPaid", 300.0),
        _pension_fact(_DB + "SettlementsBenefitObligation", 20.0),
        _pension_fact(
            _DB + "ForeignCurrencyExchangeRateChangesBenefitObligation", -40.0
        ),
        _pension_fact(_DB + "ActuarialGainLoss", 60.0),
        _pension_fact(_DB + "Curtailments", 5.0),
        _pension_fact(_DB + "PlanAmendments", 15.0),
        _pension_fact(_DB + "SpecialTerminationBenefits", 25.0),
    ]


def test_pension_funded_status_verifies_both_rollforwards() -> None:
    """Both rollforwards and the funded status verify by identity."""
    graph = _build_pension(
        _pension_facts(), axis_qname=_PENSION_AXIS, member_qname=_PENSION_MEMBER
    )
    assert graph.plan_assets.opening == 1000.0
    assert graph.plan_assets.closing == 1000.0
    assert graph.plan_assets.movements["actual_return"] == 100.0
    assert graph.plan_assets.movements["benefits_paid"] == 300.0
    assert graph.plan_assets.verified is True
    assert graph.plan_assets.discrepancy == 0.0
    assert graph.obligation.opening == 1200.0
    assert graph.obligation.closing == 1225.0
    assert graph.obligation.movements["actuarial"] == 60.0
    assert graph.obligation.verified is True
    assert graph.obligation.discrepancy == 0.0
    assert graph.funded_status == -225.0
    assert graph.funded_status_filed == -225.0
    assert graph.funded_verified is True
    assert graph.missing_components == ()
    assert dict(graph.dimensions) == _PENSION_DIMS


def test_pension_funded_status_reports_gap_and_missing_components() -> None:
    """An unreconciled closing serves with its gap and missing roles named."""
    facts = [
        _pension_fact(_DB + "FairValueOfPlanAssets", 1000.0, instant="2023-12-31"),
        _pension_fact(_DB + "FairValueOfPlanAssets", 900.0, instant="2024-12-31"),
        _pension_fact(_DB + "BenefitObligation", 1200.0, instant="2023-12-31"),
        _pension_fact(_DB + "BenefitObligation", 1300.0, instant="2024-12-31"),
        _pension_fact(_DB + "ServiceCost", 150.0),
    ]
    graph = _build_pension(
        facts, axis_qname=_PENSION_AXIS, member_qname=_PENSION_MEMBER
    )
    assert graph.plan_assets.verified is False
    assert graph.plan_assets.discrepancy == -100.0
    assert graph.obligation.verified is False
    assert graph.obligation.discrepancy == -50.0
    assert "actual_return" in graph.missing_components
    assert "interest_cost" in graph.missing_components
    assert "actuarial" in graph.missing_components
    assert graph.funded_status == -400.0
    assert graph.funded_verified is None


def test_pension_funded_status_reports_filed_status_mismatch() -> None:
    """A filed funded status that disagrees with the closings is a gap."""
    facts = _pension_facts()
    facts[4] = _pension_fact(_DB + "FundedStatusOfPlan", -200.0, instant="2024-12-31")
    graph = _build_pension(
        facts, axis_qname=_PENSION_AXIS, member_qname=_PENSION_MEMBER
    )
    assert graph.plan_assets.verified is True
    assert graph.obligation.verified is True
    assert graph.funded_status == -225.0
    assert graph.funded_discrepancy == 25.0
    assert graph.funded_verified is False


_EQ_AXIS = "us-gaap:StatementEquityComponentsAxis"
_EQ_TOTAL = "us-gaap:StockholdersEquity"
_EQ_RE = "us-gaap:RetainedEarningsMember"
_EQ_AOCI = "us-gaap:AccumulatedOtherComprehensiveIncomeMember"
_EQ_TREASURY = "us-gaap:TreasuryStockCommonMember"
_EQ_COMMON = "us-gaap:CommonStockMember"


def _equity_fact(
    qname: str,
    value: float,
    member: str | None = None,
    instant: str | None = None,
) -> XbrlFact:
    dims = {_EQ_AXIS: member} if member else {}
    if instant is not None:
        return _fact(
            qname, value, period_type="instant", instant_date=instant, dimensions=dims
        )
    return _fact(
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        dimensions=dims,
    )


def _build_equity(facts: list[XbrlFact], **kw: object):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_equity_rollforward(facts, records, taxonomy, **kw)  # type: ignore[arg-type]


def test_equity_rollforward_verifies_components_and_total() -> None:
    """Components verify by identity; OCI decompositions never double count."""
    facts = [
        _equity_fact(_EQ_TOTAL, 1500.0, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1750.0, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1300.0, member=_EQ_RE, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 500.0, member=_EQ_AOCI, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 450.0, member=_EQ_AOCI, instant="2024-12-31"),
        _equity_fact("us-gaap:NetIncomeLoss", 400.0, member=_EQ_RE),
        _equity_fact("us-gaap:DividendsCommonStockCash", 100.0, member=_EQ_RE),
        _equity_fact(
            "us-gaap:OtherComprehensiveIncomeLossNetOfTax", -50.0, member=_EQ_AOCI
        ),
        _equity_fact(
            "us-gaap:OtherComprehensiveIncomeLossBeforeReclassificationsNetOfTax",
            999.0,
            member=_EQ_AOCI,
        ),
        _equity_fact(
            "us-gaap:OtherComprehensiveIncomeLossTaxPortionAttributableToParent1",
            888.0,
            member=_EQ_AOCI,
        ),
    ]
    graph = _build_equity(facts)
    assert graph.balance_concept == _EQ_TOTAL
    assert graph.axis_qname == _EQ_AXIS
    assert graph.opening == 1500.0
    assert graph.closing == 1750.0
    assert graph.verified is True
    assert graph.components_verified is True
    assert set(graph.antichain_members) == {_EQ_RE, _EQ_AOCI}
    retained = graph.component(_EQ_RE)
    assert retained is not None
    assert retained.movements == {"net_income": 400.0, "dividends": -100.0}
    assert retained.verified is True
    aoci = graph.component(_EQ_AOCI)
    assert aoci is not None
    assert aoci.movements == {"oci": -50.0}
    assert aoci.verified is True
    assert graph.missing_components == ()


def test_equity_rollforward_signs_treasury_acquisitions_on_treasury_only() -> None:
    """Acquired cost subtracts on the treasury member and is ignored elsewhere."""
    facts = [
        _equity_fact(_EQ_TOTAL, 900.0, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 750.0, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 100.0, member=_EQ_COMMON, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 100.0, member=_EQ_COMMON, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, -200.0, member=_EQ_TREASURY, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, -350.0, member=_EQ_TREASURY, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2024-12-31"),
        _equity_fact(
            "us-gaap:TreasuryStockValueAcquiredCostMethod", 200.0, member=_EQ_TREASURY
        ),
        _equity_fact(
            "us-gaap:TreasuryStockValueAcquiredCostMethod", 999.0, member=_EQ_COMMON
        ),
        _equity_fact("x:TreasuryStockValueReissued", 50.0, member=_EQ_TREASURY),
    ]
    graph = _build_equity(facts)
    treasury = graph.component(_EQ_TREASURY)
    assert treasury is not None
    assert treasury.movements == {
        "treasury_acquired": -200.0,
        "treasury_reissued": 50.0,
    }
    assert treasury.verified is True
    common = graph.component(_EQ_COMMON)
    assert common is not None
    assert common.movements == {}
    assert common.verified is True
    assert graph.verified is True


def test_equity_rollforward_reports_gap_and_missing_opening() -> None:
    """An unreconciled component serves with its gap; a missing leg is named."""
    facts = [
        _equity_fact(_EQ_TOTAL, 1000.0, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2024-12-31"),
        _equity_fact("us-gaap:NetIncomeLoss", 400.0, member=_EQ_RE),
    ]
    graph = _build_equity(facts)
    retained = graph.component(_EQ_RE)
    assert retained is not None
    assert retained.opening is None
    assert retained.verified is None
    assert graph.verified is None
    assert "RetainedEarningsMember:opening_balance" in graph.missing_components
    facts.append(_equity_fact(_EQ_TOTAL, 900.0, member=_EQ_RE, instant="2023-12-31"))
    facts.append(_equity_fact(_EQ_TOTAL, 900.0, instant="2023-12-31"))
    graph = _build_equity(facts)
    retained = graph.component(_EQ_RE)
    assert retained is not None
    assert retained.computed_closing == 1300.0
    assert retained.verified is False
    assert retained.discrepancy == -300.0


_DIM_DOMAIN = "http://xbrl.org/int/dim/arcrole/dimension-domain"
_DIM_DEFAULT = "http://xbrl.org/int/dim/arcrole/dimension-default"
_DOMAIN_MEMBER = "http://xbrl.org/int/dim/arcrole/domain-member"
_EQ_DOMAIN = "us-gaap:EquityComponentDomain"
_EQ_PARENT = "us-gaap:ParentMember"


def _def_arcs(
    axis: str, domain: str, edges: list[tuple[str, str]]
) -> tuple[DefinitionArc, ...]:
    arcs = [
        DefinitionArc(axis, domain, _DIM_DOMAIN),
        DefinitionArc(axis, domain, _DIM_DEFAULT),
    ]
    arcs.extend(DefinitionArc(parent, child, _DOMAIN_MEMBER) for parent, child in edges)
    return tuple(arcs)


def test_segment_breakdown_excludes_subsumed_members_from_arcs() -> None:
    """An aggregate member replaces its subsumed members declaratively."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 1000.0, {_BIZ_AXIS: "x:AllMember"}),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}),
        _segment_fact(_REV, 400.0, {_BIZ_AXIS: "x:BetaMember"}),
    ]
    arcs = _def_arcs(
        _BIZ_AXIS,
        "x:SegmentDomain",
        [
            ("x:SegmentDomain", "x:AllMember"),
            ("x:AllMember", "x:AlphaMember"),
            ("x:AllMember", "x:BetaMember"),
        ],
    )
    graph = _build_segments(
        facts, concept_qname=_REV, axis_qname=_BIZ_AXIS, definition_arcs=arcs
    )
    assert {m.member_qname: m.value for m in graph.members} == {"x:AllMember": 1000.0}
    assert graph.verified is True
    fallback = _build_segments(facts, concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert len(fallback.members) == 3
    assert fallback.verified is False


def _equity_parent_facts() -> list[XbrlFact]:
    return [
        _equity_fact(_EQ_TOTAL, 1500.0, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1750.0, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1300.0, member=_EQ_RE, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 500.0, member=_EQ_AOCI, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 450.0, member=_EQ_AOCI, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1500.0, member=_EQ_PARENT, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1750.0, member=_EQ_PARENT, instant="2024-12-31"),
        _equity_fact("us-gaap:NetIncomeLoss", 400.0, member=_EQ_RE),
        _equity_fact("us-gaap:DividendsCommonStockCash", 100.0, member=_EQ_RE),
        _equity_fact(
            "us-gaap:OtherComprehensiveIncomeLossNetOfTax", -50.0, member=_EQ_AOCI
        ),
    ]


def test_equity_antichain_from_frontier_excludes_subsumed() -> None:
    """A summed member subsumed by another summed member is excluded."""
    arcs = _def_arcs(
        _EQ_AXIS,
        _EQ_DOMAIN,
        [(_EQ_DOMAIN, _EQ_PARENT), (_EQ_PARENT, _EQ_RE), (_EQ_PARENT, _EQ_AOCI)],
    )
    graph = _build_equity(_equity_parent_facts(), definition_arcs=arcs)
    assert graph.antichain_members == (_EQ_PARENT,)
    assert graph.components_verified is True


def test_equity_frontier_keeps_declared_siblings_unlike_search() -> None:
    """Siblings declared flat stay in the antichain; the search drops one."""
    arcs = _def_arcs(
        _EQ_AXIS,
        _EQ_DOMAIN,
        [(_EQ_DOMAIN, _EQ_PARENT), (_EQ_DOMAIN, _EQ_RE), (_EQ_DOMAIN, _EQ_AOCI)],
    )
    graph = _build_equity(_equity_parent_facts(), definition_arcs=arcs)
    assert set(graph.antichain_members) == {_EQ_PARENT, _EQ_RE, _EQ_AOCI}
    assert graph.components_sum == 3500.0
    assert graph.components_verified is False
    fallback = _build_equity(_equity_parent_facts())
    assert fallback.antichain_members == (_EQ_PARENT,)
    assert fallback.components_verified is True
