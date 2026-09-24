"""Unit tests for declarative RuleEngine and zero-corruption invariant."""

from __future__ import annotations

from defs.text.reflow.tools.clustering.context import BlockContext
from defs.text.reflow.tools.clustering.rules import (
    Rule,
    RuleEngine,
    SynergyRule,
)
from defs.text.reflow.tools.clustering.tests.test_context import (
    SAMPLE_CHECKBOX,
    SAMPLE_FINANCIAL_BRIDGE,
    SAMPLE_PROSE,
    SAMPLE_TABLE,
)
from defs.text.reflow.types import ACTION_PRESERVE, ACTION_UNWRAP


def test_rule_engine_preserves_table() -> None:
    engine = RuleEngine()
    ctx = BlockContext(SAMPLE_TABLE)
    decision = engine.decide(ctx)
    assert decision.action == ACTION_PRESERVE
    assert "hard_preserve" in decision.trace


def test_rule_engine_preserves_checkbox() -> None:
    engine = RuleEngine()
    ctx = BlockContext(SAMPLE_CHECKBOX)
    decision = engine.decide(ctx)
    assert decision.action == ACTION_PRESERVE
    assert decision.trace == "hard_preserve_checkbox"


def test_rule_engine_preserves_financial_bridge() -> None:
    engine = RuleEngine()
    ctx = BlockContext(SAMPLE_FINANCIAL_BRIDGE)
    decision = engine.decide(ctx)
    assert decision.action == ACTION_PRESERVE
    assert decision.trace == "hard_preserve_financial_bridge"


def test_rule_engine_unwraps_clean_prose() -> None:
    engine = RuleEngine()
    ctx = BlockContext(SAMPLE_PROSE)
    decision = engine.decide(ctx)
    assert decision.action == ACTION_UNWRAP
    assert "unwrap" in decision.trace


def test_custom_rule_with_synergy() -> None:
    rule = Rule(
        name="test_synergy_rule",
        action=ACTION_UNWRAP,
        confidence=0.88,
        synergies=(
            SynergyRule(
                name="test_syn",
                group_names=("linguistic_flow", "interline_wrapping"),
                min_total_active=2,
                min_per_group=1,
            ),
        ),
    )
    engine = RuleEngine(rules=[rule])
    ctx = BlockContext(SAMPLE_PROSE)
    decision = engine.decide(ctx)
    assert decision.action == ACTION_UNWRAP
    assert decision.trace == "test_synergy_rule"
