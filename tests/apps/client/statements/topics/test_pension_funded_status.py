from __future__ import annotations

from edgar_sec.apps.client.core.facts import build_display_records
from edgar_sec.apps.client.statements.rollforwards import build_pension_funded_status
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.apps.client.statements.topics.topic_fixtures import _fact

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
