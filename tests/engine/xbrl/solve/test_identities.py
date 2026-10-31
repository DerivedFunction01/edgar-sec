"""Unit tests for independent accounting conservation identities."""

from tests.support import fixture_path
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.solve.identities import (
    balance_sign,
    evaluate_composition,
    identity_discrepancy,
    identity_verified,
    movement_sign,
    signed_rollforward_total,
    verify_all_accounting_identities,
    verify_balance_sheet_identity,
    verify_dimensional_rollup,
    verify_eps_identity,
    verify_gross_profit_identity,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.parsing.instance_parser import parse_instance_facts
from edgar_sec.engine.xbrl.schema.models import XbrlFact


def test_balance_sheet_identity_from_parsed_facts() -> None:
    """Verify Assets == Liabilities + Equity holds on real parsed facts."""
    xml_data = fixture_path("xbrl/msft-20240630_htm.xml").read_bytes()
    facts = parse_instance_facts(xml_data, "0000950170-24-087843")

    outcome = verify_balance_sheet_identity(facts)
    assert outcome is not None
    assert outcome.passed
    assert outcome.lhs_value == 512163000000.0
    assert outcome.rhs_value == 512163000000.0
    assert outcome.discrepancy == 0.0


def test_gross_profit_identity_from_parsed_facts() -> None:
    """Verify GrossProfit == Revenues - COGS holds on real parsed facts."""
    xml_data = fixture_path("xbrl/msft-20240630_htm.xml").read_bytes()
    facts = parse_instance_facts(xml_data, "0000950170-24-087843")

    outcome = verify_gross_profit_identity(facts)
    assert outcome is not None
    assert outcome.passed
    assert outcome.lhs_value == 169295000000.0
    assert outcome.rhs_value == 169295000000.0
    assert outcome.discrepancy == 0.0


def test_dimensional_rollup_identity() -> None:
    """Verify dimensional member sum matches consolidated total."""
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(
            accession=acc,
            concept_qname="us-gaap:Revenues",
            value=100.0,
            dimensions={},
        ),
        XbrlFact(
            accession=acc,
            concept_qname="us-gaap:Revenues",
            value=60.0,
            dimensions={"axis": "segA"},
        ),
        XbrlFact(
            accession=acc,
            concept_qname="us-gaap:Revenues",
            value=40.0,
            dimensions={"axis": "segB"},
        ),
    ]

    outcome = verify_dimensional_rollup(facts, "us-gaap:Revenues", "axis")
    assert outcome is not None
    assert outcome.passed
    assert outcome.lhs_value == 100.0
    assert outcome.rhs_value == 100.0
    assert outcome.discrepancy == 0.0


def test_verify_all_accounting_identities() -> None:
    """Verify comprehensive conservation evaluation across statements."""
    xml_data = fixture_path("xbrl/msft-20240630_htm.xml").read_bytes()
    facts = parse_instance_facts(xml_data, "0000950170-24-087843")

    results = verify_all_accounting_identities(facts)
    assert len(results) >= 2
    assert all(r.passed for r in results)


def _duration_fact(qname: str, value: float, **kw: object) -> XbrlFact:
    return XbrlFact(
        AccessionNumber("0000950170-24-087843"),
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        **kw,  # type: ignore[arg-type]
    )


def test_eps_identity_prefers_common_numerator_over_filed_total() -> None:
    """Common-attributable income, not the NCI-inclusive total, is divided."""
    facts = [
        _duration_fact("us-gaap:EarningsPerShareBasic", 2.5, decimals=2),
        _duration_fact("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", 400.0),
        _duration_fact(
            "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic", 1000.0
        ),
        _duration_fact("us-gaap:ProfitLoss", 1200.0),
    ]

    outcome = verify_eps_identity(facts)
    assert outcome is not None
    assert outcome.identity_name == "ID_EPS_BASIC"
    assert outcome.passed
    assert outcome.rhs_value == 2.5
    assert outcome.tolerance == 0.005


def test_eps_identity_prefers_the_same_variant_numerator() -> None:
    """A variant-less common numerator does not displace the filed variant."""
    facts = [
        _duration_fact("us-gaap:EarningsPerShareBasic", 19.79, decimals=2),
        _duration_fact("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", 1000.0),
        _duration_fact("jpm:NetIncomeApplicableToCommonEquity", 19907.0),
        _duration_fact(
            "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic", 19790.0
        ),
    ]

    outcome = verify_eps_identity(facts)
    assert outcome is not None
    assert outcome.passed
    assert outcome.rhs_value == 19.79


def test_eps_identity_falls_back_to_net_bottom_line() -> None:
    facts = [
        _duration_fact("us-gaap:EarningsPerShareDiluted", 1.91, decimals=2),
        _duration_fact(
            "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", 1000.0
        ),
        _duration_fact("us-gaap:NetIncomeLoss", 1913.0),
    ]

    outcome = verify_eps_identity(facts, diluted=True)
    assert outcome is not None
    assert outcome.passed
    assert outcome.discrepancy == -0.003


def test_eps_identity_ignores_diluted_share_adjustment_fact() -> None:
    """The adjustment shares one atom with the diluted total; residuals decide."""
    facts = [
        _duration_fact("us-gaap:EarningsPerShareDiluted", 2.0, decimals=2),
        _duration_fact(
            "us-gaap:WeightedAverageNumberDilutedSharesOutstandingAdjustment", 10.0
        ),
        _duration_fact(
            "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", 500.0
        ),
        _duration_fact("us-gaap:NetIncomeLoss", 1000.0),
    ]

    outcome = verify_eps_identity(facts, diluted=True)
    assert outcome is not None
    assert outcome.passed
    assert outcome.rhs_value == 2.0


def test_eps_identity_reports_a_beyond_precision_miss() -> None:
    facts = [
        _duration_fact("us-gaap:EarningsPerShareBasic", 2.51, decimals=2),
        _duration_fact("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", 400.0),
        _duration_fact("us-gaap:NetIncomeLoss", 1000.0),
    ]

    outcome = verify_eps_identity(facts)
    assert outcome is not None
    assert not outcome.passed
    assert outcome.discrepancy == 0.01


def test_eps_identity_returns_none_without_a_diluted_share_fact() -> None:
    """A filing that files no diluted denominator gets no substituted one."""
    facts = [
        _duration_fact("us-gaap:EarningsPerShareDiluted", 7.84, decimals=2),
        _duration_fact("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", 400.0),
        _duration_fact("us-gaap:NetIncomeLoss", 3136.0),
    ]

    assert verify_eps_identity(facts, diluted=True) is None
    outcome = verify_eps_identity(facts)
    assert outcome is None  # no basic EPS fact filed either


def test_verify_all_includes_eps_identities() -> None:
    facts = [
        _duration_fact("us-gaap:EarningsPerShareBasic", 2.5, decimals=2),
        _duration_fact("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", 400.0),
        _duration_fact("us-gaap:NetIncomeLoss", 1000.0),
    ]

    names = {r.identity_name for r in verify_all_accounting_identities(facts)}
    assert names == {"ID_EPS_BASIC"}


def test_balance_sheet_identity_uses_the_requested_fact_scope() -> None:
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(
            acc,
            "us-gaap:Assets",
            100.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-06-30",
        ),
        XbrlFact(
            acc,
            "us-gaap:Assets",
            80.0,
            unit="USD",
            period_type="instant",
            instant_date="2023-06-30",
        ),
        XbrlFact(
            acc,
            "us-gaap:Liabilities",
            60.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-06-30",
        ),
        XbrlFact(
            acc,
            "us-gaap:StockholdersEquity",
            40.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-06-30",
        ),
    ]
    scope = FactScope(
        accession="0000950170-24-087843",
        instant_date="2024-06-30",
        unit="USD",
    )

    assert verify_balance_sheet_identity(facts) is None
    outcome = verify_balance_sheet_identity(facts, scope=scope)
    assert outcome is not None
    assert outcome.passed
    assert outcome.lhs_value == 100.0
    assert outcome.rhs_value == 100.0


def test_signed_rollforward_total_applies_signs_and_skips_missing() -> None:
    """Signed components add to the opening; missing values contribute zero."""
    total = signed_rollforward_total(100.0, ((30.0, 1.0), (12.0, -1.0), (None, -1.0)))
    assert total == 118.0
    assert signed_rollforward_total(None, ((30.0, 1.0),)) is None


def test_identity_discrepancy_and_verified_none_semantics() -> None:
    """A missing side yields no gap and no verdict, never a verdict of false."""
    assert identity_discrepancy(118.0, 118.0) == 0.0
    assert identity_discrepancy(None, 118.0) is None
    assert identity_verified(118.0, 118.4) is True
    assert identity_verified(118.0, 120.0) is False
    assert identity_verified(None, 118.0) is None


def test_movement_sign_uses_declared_valence() -> None:
    """The evaluator's sign source is the taxonomy valence data."""
    assert movement_sign("level3", "gains_oci", "liability") == -1.0
    assert movement_sign("level3", "gains_oci", "asset") == 1.0
    assert movement_sign("pension", "settlements", "assets") == -1.0


def test_evaluate_composition_sums_present_roles_only() -> None:
    """A declared composition fires on its present legs, else abstains."""
    both = evaluate_composition("debt_total", {"current": 30.0, "noncurrent": 70.0})
    assert both == 100.0
    one = evaluate_composition("debt_total", {"current": 30.0, "noncurrent": None})
    assert one == 30.0
    assert evaluate_composition("debt_total", {"current": None}) is None
    fx = evaluate_composition(
        "cash_change_including_fx", {"change_excluding_fx": 50.0, "fx_effect": -4.0}
    )
    assert fx == 46.0


def test_balance_sign_uses_declared_normal_balance() -> None:
    """Debit-normal heads enter positively, credit-normal negatively."""
    assert balance_sign("H_ASSET") == 1.0
    assert balance_sign("H_LIABILITY") == -1.0
    assert balance_sign("H_EQUITY") == -1.0
