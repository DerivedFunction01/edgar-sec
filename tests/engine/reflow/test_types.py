"""Decision vocabulary, action constants, and the injected policy contract.

The policy is the seam that keeps this package free of any form-family or
taxonomy import, so the tests here pin what a caller gets for free and what it
has to supply.
"""

from __future__ import annotations

from edgar_sec.engine.reflow.types import (
    _MIN_PROSE_ALPHA_DENSITY,
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    ReflowResult,
    SpanDecision,
)


def test_action_constants_are_distinct_stable_strings() -> None:
    actions = (ACTION_UNWRAP, ACTION_PRESERVE, ACTION_TAG_AND_PRESERVE)
    assert actions == ("unwrap", "preserve", "tag_and_preserve")
    assert len(set(actions)) == 3


def test_min_prose_alpha_density_is_the_documented_floor() -> None:
    assert _MIN_PROSE_ALPHA_DENSITY == 0.55


def test_policy_defaults_refuse_every_optional_transform() -> None:
    policy = ReflowPolicy()
    assert policy.unwrap_pre_body_prose is False
    assert policy.split_structural_boundaries is True
    assert policy.split_bullet_items is True
    assert policy.relax_prose_layout_gaps is False
    assert policy.unwrap_bullet_continuations is False
    assert policy.tag_untagged_tables is True
    assert policy.split_table_intro is None


def test_policy_predicates_default_to_absent() -> None:
    policy = ReflowPolicy()
    assert policy.is_checkbox_answer_line is None
    assert policy.is_page_boundary_line is None
    assert policy.is_structural_line is None
    assert policy.is_table_bridge_line is None
    assert policy.is_table_tail_line is None


def test_policy_is_frozen() -> None:
    policy = ReflowPolicy()
    try:
        policy.unwrap_pre_body_prose = True
    except AttributeError:
        return
    raise AssertionError("ReflowPolicy accepted a mutation")


def test_policy_accepts_an_injected_splitter() -> None:
    def splitter(
        lines: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return lines[:1], lines[1:]

    policy = ReflowPolicy(split_table_intro=splitter)
    assert policy.split_table_intro is splitter


def test_span_decision_defaults_evidence_and_trace_empty() -> None:
    decision = SpanDecision(ACTION_PRESERVE, 3, 9, 1.0)
    assert decision.evidence == ()
    assert decision.trace == ""


def test_reflow_result_defaults_to_no_decisions_and_no_regions() -> None:
    result = ReflowResult("body")
    assert result.text == "body"
    assert result.decisions == ()
    assert result.protected_tables == ()
    assert result.protected_signatures == ()
