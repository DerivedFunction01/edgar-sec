"""Cross-firm rule weights: intra-firm full, cross-firm discounted."""

from edgar_sec.engine.xbrl.solve.counter_solver import CounterSolver
from edgar_sec.engine.xbrl.evidence.evidence import UnificationRule


def test_cross_firm_rule_weight_discounting() -> None:
    """Verify intra-firm full weight vs cross-firm prior discounting."""
    rule = UnificationRule(
        rule_id="R_MSFT_CLOUD",
        target_node="us-gaap:Revenues",
        concept_qname="msft:CloudServicesRevenue",
        weight=1.0,
        scope=("MSFT", "Technology", "*"),
    )

    w_self = CounterSolver.evaluate_rule_weight(rule, firm="MSFT", sector="Technology")
    assert w_self == 1.0

    w_cross = CounterSolver.evaluate_rule_weight(
        rule, firm="GOOGL", sector="Technology"
    )
    assert w_cross == 0.5

    w_mismatch = CounterSolver.evaluate_rule_weight(rule, firm="XOM", sector="Energy")
    assert w_mismatch == 0.0
