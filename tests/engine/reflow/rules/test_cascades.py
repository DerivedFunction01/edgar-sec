"""The ordered decision cascade and the block-to-decision mapping.

Rule order is the contract this module pins. The first rule whose conditions
hold decides the block and nothing after it is consulted, which is why every
hard protection has to precede every permissive fallback; a cascade that put the
general prose rules first would let an ambiguous block through as unwrap.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.reflow.features.context import BlockContext
from edgar_sec.engine.reflow.features.geometry import _compute_features
from edgar_sec.engine.reflow.rules.cascades import (
    FEATURE_GROUPS,
    FeatureThreshold,
    GroupQuota,
    Rule,
    RuleEngine,
    SynergyRule,
    _decide,
    decide_block,
)
from edgar_sec.engine.reflow.rules.thresholds import FEATURE_REGISTRY
from edgar_sec.engine.reflow.types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    SpanDecision,
)

PROSE = (
    "We are an enterprise software company",
    "founded in 1998 that sells products",
    "across multiple market segments today.",
)

TABLE = (
    "Revenue by segment       2024       2023",
    "  Automotive             $1,200     $1,100",
    "  Industrial             $2,050     $1,980",
)

PRODUCTION_POLICY = ReflowPolicy(
    is_checkbox_answer_line=lambda line: "Yes [X]" in line,
    is_table_bridge_line=lambda line: line.isupper(),
)

# Every group name is a declared set of registered features, so a group cannot
# name a measurement the cascade has no predicate for.
EXPECTED_GROUPS = {
    "linguistic_flow",
    "interline_wrapping",
    "row_dynamics",
    "window_density",
    "table_geometry",
    "structural_anchors",
}


def _context(lines: tuple[str, ...]) -> BlockContext:
    return BlockContext(lines, PRODUCTION_POLICY)


def test_feature_groups_are_the_documented_six() -> None:
    assert set(FEATURE_GROUPS) == EXPECTED_GROUPS


@pytest.mark.parametrize("group", sorted(FEATURE_GROUPS))
def test_every_group_member_is_a_registered_feature(group: str) -> None:
    for name in FEATURE_GROUPS[group]:
        assert name in FEATURE_REGISTRY


def test_no_feature_is_claimed_by_two_groups() -> None:
    members = [name for group in FEATURE_GROUPS.values() for name in group]
    assert len(members) == len(set(members))


def test_six_features_are_read_directly_rather_than_through_a_group() -> None:
    members = {name for group in FEATURE_GROUPS.values() for name in group}
    ungrouped = set(FEATURE_REGISTRY) - members
    # These are read by a rule's direct condition, not by a quota, so no group
    # claims them. The set is pinned: a feature quietly added to a group stops
    # being read where the calibration put it.
    assert ungrouped == {
        "continuation_col0_ratio",
        "ends_terminal_punct",
        "inset_measure_width",
        "line_count",
        "rewrap_residual",
        "starts_capital_or_indent",
    }


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        (">=", 3, True),
        (">", 3, False),
        ("<=", 3, True),
        ("<", 3, False),
        ("==", 3, True),
        ("!=", 3, False),
    ],
)
def test_feature_threshold_evaluates_every_operator(
    op: str, value: int, expected: bool
) -> None:
    context = _context(("a", "b", "c"))
    assert FeatureThreshold("line_count", op, value).evaluate(context) is expected


def test_decide_block_unwraps_ordinary_prose() -> None:
    decision = decide_block(_context(PROSE))
    assert decision.action == ACTION_UNWRAP
    assert decision.trace == "unwrap_high_confidence_prose"
    assert decision.evidence == ("ordinary_prose",)


def test_decide_block_tags_a_shared_numeric_table() -> None:
    decision = decide_block(_context(TABLE))
    assert decision.action == ACTION_TAG_AND_PRESERVE
    assert decision.evidence[0].startswith("repeated_numeric_columns:")


def test_decide_block_preserves_a_tagged_table() -> None:
    decision = decide_block(_context(("<TABLE>", "A 1", "</TABLE>")))
    assert decision.action == ACTION_PRESERVE
    assert decision.trace == "hard_preserve_table_tag"
    assert decision.confidence == 1.0


def test_decide_block_preserves_a_single_non_prose_line() -> None:
    decision = decide_block(_context(("ITEM 1. BUSINESS",)))
    assert decision.action == ACTION_PRESERVE
    assert decision.trace == "preserve_single_line_noop"


def test_decide_block_unwraps_a_single_prose_line() -> None:
    decision = decide_block(_context(("the company operates worldwide.",)))
    assert decision.action == ACTION_UNWRAP
    assert decision.trace == "unwrap_single_line_prose"


def test_decide_block_preserves_a_layout_gap_block_without_alignment() -> None:
    decision = decide_block(
        _context(
            (
                "We believe   the company will continue to grow",
                "because   demand remains strong across regions.",
            )
        )
    )
    assert decision.action == ACTION_PRESERVE
    assert decision.trace == "preserve_layout_gap_candidate"


def test_decide_block_falls_back_to_preserve_on_an_ambiguous_block() -> None:
    decision = decide_block(_context(("a", "1", "b", "2")))
    assert decision.action == ACTION_PRESERVE


def test_decide_block_line_count_argument_overrides_the_measured_count() -> None:
    context = _context(PROSE)
    assert decide_block(context, line_count=1).action == ACTION_UNWRAP
    assert decide_block(context, line_count=1).trace == "unwrap_single_line_prose"


def test_decide_block_honours_the_injected_financial_bridge() -> None:
    lines = ("LIABILITIES AND STOCKHOLDERS' EQUITY", "CURRENT ASSETS   100   90")
    assert decide_block(_context(lines)).action == ACTION_PRESERVE
    without = decide_block(BlockContext(lines))
    assert without.trace != "hard_preserve_financial_bridge"


def test_count_active_features_stops_early_when_asked() -> None:
    engine = RuleEngine()
    context = _context(PROSE)
    full, _ = engine.count_active_features(context, "linguistic_flow")
    early, active = engine.count_active_features(
        context, "linguistic_flow", (), early_stop=1
    )
    assert full > 1
    assert early == 1
    assert len(active) == 1


def test_count_active_features_honours_a_per_rule_override() -> None:
    engine = RuleEngine()
    context = _context(PROSE)
    override = (FeatureThreshold("possessive_count", ">", 1000),)
    count, active = engine.count_active_features(context, "linguistic_flow", override)
    assert "possessive_count" not in active
    assert count < len(FEATURE_GROUPS["linguistic_flow"])


def test_evaluate_rule_rejects_when_a_direct_condition_fails() -> None:
    engine = RuleEngine()
    rule = Rule(
        name="never",
        action=ACTION_PRESERVE,
        confidence=1.0,
        direct_conditions=(FeatureThreshold("line_count", ">", 1000),),
    )
    matched, _ = engine.evaluate_rule(rule, _context(PROSE))
    assert matched is False


def test_evaluate_rule_rejects_when_a_group_quota_is_not_met() -> None:
    engine = RuleEngine()
    rule = Rule(
        name="quota",
        action=ACTION_PRESERVE,
        confidence=1.0,
        group_quotas=(GroupQuota("linguistic_flow", min_active=100),),
    )
    matched, _ = engine.evaluate_rule(rule, _context(TABLE))
    assert matched is False


def test_evaluate_rule_rejects_when_a_maximum_is_exceeded() -> None:
    engine = RuleEngine()
    rule = Rule(
        name="capped",
        action=ACTION_PRESERVE,
        confidence=1.0,
        group_quotas=(GroupQuota("interline_wrapping", min_active=0, max_active=0),),
    )
    matched, _ = engine.evaluate_rule(rule, _context(PROSE))
    assert matched is False


def test_evaluate_rule_requires_every_synergy_group_and_the_total() -> None:
    engine = RuleEngine()
    rule = Rule(
        name="synergy",
        action=ACTION_PRESERVE,
        confidence=1.0,
        synergies=(SynergyRule("s", ("linguistic_flow",), min_total_active=1000),),
    )
    matched, _ = engine.evaluate_rule(rule, _context(PROSE))
    assert matched is False


def test_evaluate_rule_uses_declared_evidence_when_present() -> None:
    engine = RuleEngine()
    rule = Rule(
        name="declared",
        action=ACTION_PRESERVE,
        confidence=1.0,
        direct_conditions=(FeatureThreshold("line_count", ">", 0),),
        evidence=("declared_reason",),
    )
    matched, evidence = engine.evaluate_rule(rule, _context(PROSE))
    assert matched is True
    assert evidence == ["declared_reason"]


def test_evaluate_rule_falls_back_to_derived_evidence() -> None:
    engine = RuleEngine()
    rule = Rule(
        name="derived",
        action=ACTION_PRESERVE,
        confidence=1.0,
        direct_conditions=(FeatureThreshold("line_count", ">", 0),),
        group_quotas=(GroupQuota("interline_wrapping", min_active=0),),
    )
    matched, evidence = engine.evaluate_rule(rule, _context(PROSE))
    assert matched is True
    assert evidence[0] == "line_count>0"
    assert any(item.startswith("group:interline_wrapping") for item in evidence)


def test_evaluate_rule_uses_an_evidence_builder() -> None:
    engine = RuleEngine()
    rule = Rule(
        name="built",
        action=ACTION_PRESERVE,
        confidence=1.0,
        direct_conditions=(FeatureThreshold("line_count", ">", 0),),
        evidence_builder=lambda ctx: (f"rows:{ctx.line_count}",),
    )
    matched, evidence = engine.evaluate_rule(rule, _context(PROSE))
    assert matched is True
    assert evidence == ["rows:3"]


def test_every_hard_protection_precedes_the_general_fallbacks() -> None:
    rules = RuleEngine().rules
    names = [rule.name for rule in rules]
    fallbacks = {
        "unwrap_ordinary_prose_no_gaps",
        "preserve_layout_gap_candidate",
        "unwrap_general_prose",
        "default_preserve_ambiguous",
    }
    first_fallback = min(names.index(name) for name in fallbacks)
    last_hard = max(
        index for index, name in enumerate(names) if name.startswith("hard_preserve")
    )
    assert last_hard < first_fallback


def test_the_table_detectors_precede_the_general_fallbacks() -> None:
    names = [rule.name for rule in RuleEngine().rules]
    detectors = {
        "preserve_prose_dominant_numeric_alignment",
        "preserve_linguistic_numeric_alignment",
        "tag_preserve_shared_numeric_table",
        "tag_preserve_separator_grid",
    }
    assert all(
        names.index(name) < names.index("unwrap_ordinary_prose_no_gaps")
        for name in detectors
    )


def test_dot_leader_run_reaches_numeric_table_detection() -> None:
    lines = (
        "Consolidated statements of operations ............ 14",
        "Consolidated statements of comprehensive income .... 15",
        "Consolidated statements of cash flows ............. 16",
    )
    ctx = _context(lines)

    assert ctx.shared_numeric_columns == 1
    assert ctx.numeric_cell_row_count == 3
    decision = decide_block(ctx, len(lines))
    assert decision.action == ACTION_TAG_AND_PRESERVE
    assert decision.trace == "tag_preserve_shared_numeric_table"


def test_linguistic_numeric_alignment_is_preserved_as_prose() -> None:
    lines = (
        "      1.   Each person who is known by us to be the beneficial owner of more than",
        "           5% of the common stock,",
        "      2.   Each of our directors and executive officers and",
        "      3.   All of our directors and executive officers as a group.",
    )
    ctx = _context(lines)

    decision = decide_block(ctx, len(lines))

    assert decision.action == ACTION_PRESERVE
    assert decision.trace == "preserve_linguistic_numeric_alignment"
    assert "linguistic_numeric_prose" in decision.evidence


def test_the_single_line_rules_precede_the_multi_line_fallbacks() -> None:
    names = [rule.name for rule in RuleEngine().rules]
    assert names.index("unwrap_single_line_prose") < names.index(
        "unwrap_ordinary_prose_no_gaps"
    )
    assert names.index("preserve_single_line_noop") < names.index(
        "unwrap_ordinary_prose_no_gaps"
    )


def test_cascade_rule_names_are_the_calibrated_sequence() -> None:
    assert [rule.name for rule in RuleEngine().rules] == [
        "hard_preserve_table_tag",
        "hard_preserve_structural",
        "hard_preserve_tab",
        "hard_preserve_signature",
        "hard_preserve_checkbox",
        "hard_preserve_financial_bridge",
        "hard_preserve_column_underlines",
        "unwrap_high_confidence_prose",
        "preserve_prose_dominant_numeric_alignment",
        "preserve_linguistic_numeric_alignment",
        "tag_preserve_shared_numeric_table",
        "tag_preserve_separator_grid",
        "hard_preserve_dot_leader",
        "hard_preserve_strong_gutter",
        "hard_preserve_stub_gutter_numeric",
        "hard_preserve_numeric_aligned",
        "hard_preserve_separator_run",
        "hard_preserve_deadspace_corridor",
        "hard_preserve_exhibit_index",
        "unwrap_single_line_prose",
        "preserve_single_line_noop",
        "unwrap_ordinary_prose_no_gaps",
        "preserve_layout_gap_candidate",
        "unwrap_general_prose",
        "default_preserve_ambiguous",
    ]


def test_engine_accepts_a_custom_rule_list() -> None:
    engine = RuleEngine(
        [
            Rule(
                name="only",
                action=ACTION_UNWRAP,
                confidence=0.5,
                direct_conditions=(FeatureThreshold("line_count", ">", 0),),
                evidence=("only",),
            )
        ]
    )
    assert engine.decide(_context(PROSE)).evidence == ("only",)


def test_decide_from_a_masked_table_short_circuits_to_preserve() -> None:
    decision = _decide(_context(PROSE), len(PROSE), True)
    assert decision == SpanDecision(
        ACTION_PRESERVE,
        0,
        len(PROSE),
        1.0,
        ("protected_tagged_table",),
        "hard_preserve",
    )


def test_decide_maps_a_context_preserve_to_the_matching_trace() -> None:
    decision = _decide(_context(("<TABLE>", "A 1", "</TABLE>")), 3)
    assert decision.trace == "hard_preserve"
    decision = _decide(_context(("ITEM 1. BUSINESS",)), 1)
    assert decision.trace == "fast_noop"
    decision = _decide(
        _context(
            (
                "We believe   the company will continue to grow",
                "because   demand remains strong across regions.",
            )
        ),
        2,
    )
    assert decision.trace == "candidate_preserve"


def test_decide_maps_a_context_tag_to_the_table_trace() -> None:
    decision = _decide(_context(TABLE), len(TABLE))
    assert decision.action == ACTION_TAG_AND_PRESERVE
    assert decision.trace == "high_confidence_table"


def test_decide_accepts_a_geometry_record_instead_of_a_context() -> None:
    features = _compute_features(TABLE)
    decision = _decide(features, len(TABLE))
    assert decision.action == ACTION_TAG_AND_PRESERVE
    assert decision.evidence[0].startswith("repeated_numeric_columns:")


def test_geometry_branch_preserves_structural_and_tab_blocks() -> None:
    assert _decide(_compute_features(("<S>  <C>",)), 1).action == ACTION_PRESERVE
    assert _decide(_compute_features(("a\tb",)), 1).trace == "hard_preserve"
    assert _decide(_compute_features(("Date: March 1",)), 1).trace == "hard_preserve"
    assert _decide(_compute_features(("a ..... 1",)), 1).trace == "hard_preserve"


def test_geometry_branch_unwraps_prose_and_preserves_ambiguity() -> None:
    assert _decide(_compute_features(PROSE), len(PROSE)).action == ACTION_UNWRAP
    assert (
        _decide(
            _compute_features(
                (),
            ),
            0,
        ).action
        == ACTION_PRESERVE
    )
