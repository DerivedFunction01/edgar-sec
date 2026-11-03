from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.solve.evaluation import AggregateEvaluator
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def test_evaluator_returns_direct_fact_anchor() -> None:
    evaluator = AggregateEvaluator(
        EvidenceKnowledgeBase(load_domain_taxonomy()), AntiChainValidator()
    )
    fact = XbrlFact(AccessionNumber("0000950170-24-087843"), "us-gaap:Revenue", 12.0)

    result = evaluator.evaluate_goal("us-gaap:Revenue", [fact])

    assert result.value == 12.0
    assert result.basis == "REPORTED"


def _evaluator() -> AggregateEvaluator:
    return AggregateEvaluator(
        EvidenceKnowledgeBase(load_domain_taxonomy()), AntiChainValidator()
    )


_TARGET = "us-gaap:LiabilitiesAndStockholdersEquity"
_ARCS = (
    CalculationArc(_TARGET, "us-gaap:Liabilities", weight=1.0),
    CalculationArc(_TARGET, "us-gaap:CommitmentsAndContingencies", weight=1.0),
    CalculationArc(_TARGET, "us-gaap:StockholdersEquity", weight=1.0),
)


def test_calc_derivation_skips_nil_reported_child() -> None:
    """A nil-reported calc child contributes nothing to the calc sum."""
    acc = AccessionNumber("0000000000-25-000001")
    facts = [
        XbrlFact(acc, "us-gaap:Liabilities", 100.0),
        XbrlFact(acc, "us-gaap:CommitmentsAndContingencies", None),
        XbrlFact(acc, "us-gaap:StockholdersEquity", 200.0),
    ]

    result = _evaluator().evaluate_goal(_TARGET, facts, _ARCS)

    assert result.value == 300.0
    assert result.basis == "DERIVED_EXACT"
    assert result.resolution_tier == "DERIVED_MULTI_HOP"


def test_calc_derivation_absent_child_still_blocks() -> None:
    """An absent calc child blocks the calc path; the identity fallback runs."""
    acc = AccessionNumber("0000000000-25-000001")
    facts = [
        XbrlFact(acc, "us-gaap:Liabilities", 100.0),
        XbrlFact(acc, "us-gaap:StockholdersEquity", 200.0),
    ]

    result = _evaluator().evaluate_goal(_TARGET, facts, _ARCS)

    assert result.value == 300.0
    assert result.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"


_HEADLINE = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
_GROSS_PROFIT_ARCS = (
    CalculationArc("us-gaap:GrossProfit", _HEADLINE, weight=1.0),
    CalculationArc(
        "us-gaap:GrossProfit", "us-gaap:CostOfGoodsAndServicesSold", weight=-1.0
    ),
)


def test_inverse_solve_recovers_revenue_from_the_gross_profit_formula() -> None:
    """Gross Profit's formula solved for its revenue term: margin + cost."""
    acc = AccessionNumber("0000000000-25-000001")
    facts = [
        XbrlFact(acc, "us-gaap:GrossProfit", 100.0),
        XbrlFact(acc, "us-gaap:CostOfGoodsAndServicesSold", 30.0),
    ]

    result = _evaluator().evaluate_goal(_HEADLINE, facts, _GROSS_PROFIT_ARCS)

    assert result.value == 130.0
    assert result.basis == "DERIVED_EXACT"
    assert result.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"


def test_lone_margin_fact_never_derives_revenue() -> None:
    """A single participation edge is not an identity: no derivation."""
    acc = AccessionNumber("0000000000-25-000001")
    facts = [XbrlFact(acc, "us-gaap:GrossProfit", 100.0)]

    result = _evaluator().evaluate_goal("us-gaap:Revenues", facts)

    assert result.value is None
    assert result.basis == "NOT_AVAILABLE"


def _eps_leg(qname: str, value: float, unit: str) -> XbrlFact:
    return XbrlFact(
        AccessionNumber("0000000000-25-000001"),
        qname,
        value,
        unit=unit,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
    )


def test_eps_derived_from_filed_legs_via_the_identity() -> None:
    """An unfiled EPS resolves as numerator over weighted-average shares."""
    facts = [
        _eps_leg("us-gaap:NetIncomeLoss", 1000.0, "USD"),
        _eps_leg(
            "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", 400.0, "shares"
        ),
    ]

    result = _evaluator().evaluate_goal("us-gaap:EarningsPerShareBasic", facts)

    assert result.value == 2.5
    assert result.basis == "DERIVED_EXACT"
    assert result.resolution_tier == "ACCOUNTING_IDENTITY"


def test_eps_derivation_abstains_without_a_leg() -> None:
    """A missing share leg leaves EPS unresolved, never substituted."""
    facts = [_eps_leg("us-gaap:NetIncomeLoss", 1000.0, "USD")]

    result = _evaluator().evaluate_goal("us-gaap:EarningsPerShareBasic", facts)

    assert result.value is None
    assert result.basis == "NOT_AVAILABLE"


def test_filed_eps_stays_the_direct_anchor_over_the_identity() -> None:
    """A filed EPS answers as the reported fact, not the derived quotient."""
    facts = [
        _eps_leg("us-gaap:EarningsPerShareBasic", 2.5, "USD/shares"),
        _eps_leg("us-gaap:NetIncomeLoss", 1000.0, "USD"),
        _eps_leg(
            "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", 400.0, "shares"
        ),
    ]

    result = _evaluator().evaluate_goal("us-gaap:EarningsPerShareBasic", facts)

    assert result.value == 2.5
    assert result.basis == "REPORTED"
    assert result.resolution_tier == "DIRECT_ANCHOR"


def test_inverse_solve_blocked_without_the_filed_total() -> None:
    """Solving for a term needs the formula's total filed as a fact."""
    acc = AccessionNumber("0000000000-25-000001")
    facts = [XbrlFact(acc, "us-gaap:CostOfGoodsAndServicesSold", 30.0)]

    result = _evaluator().evaluate_goal(_HEADLINE, facts, _GROSS_PROFIT_ARCS)

    assert result.value is None
    assert result.basis == "NOT_AVAILABLE"
