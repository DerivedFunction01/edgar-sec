"""Unit tests for the filing-catalog operator wizard.

The wizard is a presentation layer over the CLI. These tests pin the three
actions it exposes and the delegation that keeps the two surfaces from drifting
apart.

The menu is three actions, not the five v1 offered: ``expand`` and
``--scope policy`` are reachable from the CLI but have no menu entry. That is a
deliberate reduction, and it is asserted here as the current contract rather
than as v1 parity.
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from edgar_sec.pipelines.filing_catalog import cli, operator
from edgar_sec.pipelines.filing_catalog.operator import (
    MENU_TITLE,
    build_operator_menu,
    main,
)

# --- the menu --------------------------------------------------------------


def test_the_menu_exposes_three_actions() -> None:
    labels = [action.label.lower() for action in build_operator_menu()]
    assert len(labels) == 3
    assert any("report" in label for label in labels)
    assert any("materialize" in label for label in labels)
    assert any("catalog" in label and "plan" in label for label in labels)


def test_menu_actions_are_numbered_in_order() -> None:
    keys = [action.key for action in build_operator_menu()]
    assert keys == ["1", "2", "3"]


def test_every_action_is_callable() -> None:
    for action in build_operator_menu():
        assert callable(action.callback)


# --- delegation ------------------------------------------------------------


def test_actions_delegate_to_the_cli_commands() -> None:
    """The wizard must not reimplement behaviour the CLI already owns."""
    for action in build_operator_menu():
        assert action.callback.__module__ == operator.__name__
    assert operator.cmd_status is cli.cmd_status
    assert operator.cmd_plan is cli.cmd_plan
    assert operator.cmd_materialize is cli.cmd_materialize


def test_a_supplied_command_bypasses_the_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a command on argv the operator is the CLI, not a prompt."""
    calls: list[list[str]] = []
    monkeypatch.setattr(operator, "cli_main", lambda argv: calls.append(argv) or 0)
    assert main(["status"]) == 0
    assert calls == [["status"]]


def test_the_menu_title_names_the_phase() -> None:
    assert "Filing Catalog" in MENU_TITLE


# --- prompt plumbing -------------------------------------------------------


def test_namespace_carries_every_field_the_commands_read() -> None:
    """A prompt-driven namespace must satisfy the command it dispatches to.

    The commands read a fixed set of attributes, so a namespace missing one
    fails with AttributeError at the prompt rather than at the user.
    """
    namespace = operator._namespace("plan", catalog="current", forms="10-K 8-K")
    assert isinstance(namespace, argparse.Namespace)
    assert namespace.command == "plan"
    assert namespace.forms == ["10-K", "8-K"]
    for field in ("scope", "amendment", "suffixes", "limit", "artifacts"):
        assert hasattr(namespace, field), f"cmd_plan reads {field}"
    for field in ("source", "source_manifest", "batch_size"):
        assert hasattr(namespace, field), f"cmd_materialize reads {field}"


def test_a_blank_forms_prompt_means_no_filter() -> None:
    assert operator._namespace("plan", forms="").forms == []
    assert operator._namespace("plan", forms="  ").forms == []


def test_comma_and_space_separated_forms_agree() -> None:
    assert operator._namespace("plan", forms="10-K,8-K").forms == ["10-K", "8-K"]
    assert operator._namespace("plan", forms="10-K, 8-K").forms == ["10-K", "8-K"]


def test_every_prompted_action_builds_a_usable_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Drive each action with scripted answers and a stubbed command."""
    seen: list[argparse.Namespace] = []

    def _capture(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    # In menu order: status asks for the artifacts root; materialize asks for
    # the root then the source; plan asks for the root, catalog, then forms.
    answers = iter(["", "art", "src", "art", "cat-1", "10-K"])
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: next(answers))
    for name in ("cmd_status", "cmd_plan", "cmd_materialize"):
        monkeypatch.setattr(operator, name, _capture)

    for action in build_operator_menu():
        action.callback()

    assert [namespace.command for namespace in seen] == [
        "status",
        "materialize",
        "plan",
    ]
    plan_namespace = seen[2]
    assert plan_namespace.catalog == "cat-1"
    assert plan_namespace.forms == ["10-K"]
    assert plan_namespace.scope == "deterministic"
