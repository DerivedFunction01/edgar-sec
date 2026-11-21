"""EPS identity consumption: verified identities leave quarantine."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.solve.counter_solver import CounterSolver
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from tests.engine.xbrl.solve.counter_solver.conftest import (
    _NoFallbackSolver,
    _decls,
    _reason_by_concept,
)


def _duration_fact(
    acc: AccessionNumber,
    qname: str,
    value: float,
    *,
    unit: str = "USD",
    decimals: int | None = None,
) -> XbrlFact:
    return XbrlFact(
        acc,
        qname,
        value,
        unit=unit,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        decimals=decimals,
    )


def _eps_facts(acc: AccessionNumber, eps: float) -> list[XbrlFact]:
    return [
        _duration_fact(
            acc,
            "us-gaap:EarningsPerShareBasic",
            eps,
            unit="USD/shares",
            decimals=2,
        ),
        _duration_fact(
            acc,
            "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
            400.0,
            unit="shares",
        ),
        _duration_fact(acc, "us-gaap:NetIncomeLoss", 1000.0),
    ]


def test_audit_consumes_facts_of_a_passing_eps_identity() -> None:
    """EPS, numerator, and share facts leave quarantine via the identity."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    outcome = counter.audit_filing(
        _eps_facts(acc, 2.5), target_goals=[], calculation_arcs=[]
    )
    assert len(outcome.solved_facts) == 3
    assert outcome.quarantined_facts == ()


def test_audit_names_calc_isolation_when_the_eps_identity_fails() -> None:
    """An unverified per-share fact carries the isolation verdict."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    outcome = counter.audit_filing(
        _eps_facts(acc, 9.99), target_goals=[], calculation_arcs=[]
    )
    assert _reason_by_concept(outcome) == {
        "us-gaap:EarningsPerShareBasic": "UNDIMENSIONED_CALC_ISOLATED",
        "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic": (
            "UNDIMENSIONED_NO_CALC_ROLE"
        ),
        "us-gaap:NetIncomeLoss": "UNDIMENSIONED_NO_CALC_ROLE",
    }


def test_audit_names_calc_isolation_for_a_declared_per_share_concept() -> None:
    """The verdict follows the declared type, not the concept name."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [_duration_fact(acc, "custom:DividendPerShare", 1.5, unit="USD/shares")]
    declarations = _decls("custom:DividendPerShare", item_type="xbrli:perShareItemType")
    outcome = counter.audit_filing(
        facts, target_goals=[], calculation_arcs=[], declarations=declarations
    )
    assert _reason_by_concept(outcome) == {
        "custom:DividendPerShare": "UNDIMENSIONED_CALC_ISOLATED"
    }
