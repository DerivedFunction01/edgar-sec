"""Contract tests for the `FormPlugin` record and the generic evaluator."""

from __future__ import annotations

import dataclasses

import pytest

from edgar_sec.domain.forms.common.decisions import DecisionAction, EvaluatorDecision
from edgar_sec.engine.forms.plugins.base import (
    GENERIC_FAMILY,
    FormPlugin,
    evaluate_generic,
)


def test_stage_gates_default_off() -> None:
    plugin = FormPlugin(family="8-K")
    assert plugin.enable_toc is False
    assert plugin.enable_body_start is False
    assert plugin.evaluator is None


def test_plugin_is_frozen_and_comparable() -> None:
    plugin = FormPlugin(family="10-K", enable_toc=True)
    assert plugin == FormPlugin(family="10-K", enable_toc=True)
    assert plugin != FormPlugin(family="20-F", enable_toc=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plugin.family = "10-Q"  # type: ignore[misc]


def test_evaluator_is_callable_with_the_normalized_text_alone() -> None:
    plugin = FormPlugin(family="10-K", evaluator=evaluate_generic)
    decision = plugin.evaluator("normalized text")
    assert isinstance(decision, EvaluatorDecision)
    assert decision.action is DecisionAction.PROCEED


def test_generic_family_is_the_unmodelled_form_key() -> None:
    assert GENERIC_FAMILY == "GENERIC"


def test_generic_evaluator_proceeds_with_the_primary_payload() -> None:
    decision = evaluate_generic("anything")
    assert decision.action is DecisionAction.PROCEED
    assert decision.target_exhibit is None
    assert decision.is_stub is False
    assert decision.category == "standard_full"
    assert decision.confidence == 1.0
    assert decision.metadata == {}
    assert "proceeding with primary payload" in decision.reason


def test_generic_evaluator_ignores_its_input() -> None:
    assert evaluate_generic("") == evaluate_generic("a much longer document")
