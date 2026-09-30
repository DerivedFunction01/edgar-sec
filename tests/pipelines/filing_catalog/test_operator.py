"""Unit tests for the filing-catalog operator wizard.

The wizard is a presentation layer over the CLI. These tests pin the actions it
exposes, the delegation that keeps the two surfaces from drifting apart, and the
discovery that lets an operator pick a catalog or an expansion parent instead of
typing an identifier they were never shown.

``--scope policy`` is still reachable only from the CLI: choosing a policy scope
interactively would mean authoring a quota profile, which is a design decision
rather than a menu selection. ``expand`` *is* offered, because its inputs are a
parent plan and a target size, both of which can be discovered or defaulted.
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


def test_the_menu_exposes_every_command_an_operator_can_drive() -> None:
    labels = [action.label.lower() for action in build_operator_menu()]
    assert len(labels) == 4
    assert any("report" in label for label in labels)
    assert any("materialize" in label for label in labels)
    assert any("catalog" in label and "plan" in label for label in labels)
    assert any("expand" in label for label in labels)


def test_every_cli_subcommand_is_reachable_one_way_or_the_other() -> None:
    """A command with neither a menu entry nor a documented reason is dead surface."""
    menu = " ".join(
        (action.label + " " + action.callback.__name__).lower()
        for action in build_operator_menu()
    )
    for command in ("materialize", "plan", "expand", "status"):
        assert command in menu, command


def test_menu_actions_are_numbered_in_order() -> None:
    keys = [action.key for action in build_operator_menu()]
    assert keys == ["1", "2", "3", "4"]


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
    assert operator.cmd_expand is cli.cmd_expand


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
    for field in ("parent_plan", "target_units"):
        assert hasattr(namespace, field), f"cmd_expand reads {field}"


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
    # the root then the source; plan asks for the root, catalog, then forms;
    # expand asks for the root, the parent plan, then the target size.
    answers = iter(["", "art", "src", "art", "cat-1", "10-K", "art", "1", "5000"])
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: next(answers))
    monkeypatch.setattr(operator, "discover_catalogs", lambda _paths: [])
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _paths: [
            {"plan_id": "plan-1", "scope": "policy", "unique_locators_count": 100}
        ],
    )
    for name in ("cmd_status", "cmd_plan", "cmd_materialize", "cmd_expand"):
        monkeypatch.setattr(operator, name, _capture)

    for action in build_operator_menu():
        action.callback()

    assert [namespace.command for namespace in seen] == [
        "status",
        "materialize",
        "plan",
        "expand",
    ]
    plan_namespace = seen[2]
    assert plan_namespace.catalog == "cat-1"
    assert plan_namespace.forms == ["10-K"]
    assert plan_namespace.scope == "deterministic"


# --- discovery -------------------------------------------------------------


def test_expand_resolves_a_picked_parent_to_its_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """``--parent-plan`` is a directory the operator was never shown.

    The menu offers the published policy plans by number and passes the resolved
    plan directory, so the hand-typed path is no longer the only route in.
    """
    seen: list[argparse.Namespace] = []
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: default)
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _paths: [
            {"plan_id": "plan-1", "scope": "policy", "unique_locators_count": 100},
            {"plan_id": "plan-2", "scope": "deterministic", "unique_locators_count": 5},
        ],
    )
    monkeypatch.setattr(operator, "cmd_expand", lambda args: seen.append(args) or 0)
    monkeypatch.setattr(
        operator, "resolve_filing_catalog_paths", lambda root=None: _paths(tmp_path)
    )

    operator._action_expand()

    assert len(seen) == 1
    assert seen[0].parent_plan == str(_paths(tmp_path).plan_dir("plan-1"))
    assert seen[0].target_units == 100


def test_expand_never_offers_a_plan_it_would_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys
) -> None:
    """Expansion refuses a deterministic parent, so listing one is a dead choice."""
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: default)
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _paths: [{"plan_id": "plan-2", "scope": "deterministic"}],
    )
    monkeypatch.setattr(operator, "cmd_expand", lambda args: pytest.fail("expanded"))
    monkeypatch.setattr(
        operator, "resolve_filing_catalog_paths", lambda root=None: _paths(tmp_path)
    )

    operator._action_expand()
    assert "no policy-driven plan" in capsys.readouterr().out


def test_expand_refuses_a_contraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys
) -> None:
    """A smaller target is a contraction; the command refuses it, so the menu does."""
    monkeypatch.setattr(
        operator, "resolve_filing_catalog_paths", lambda root=None: _paths(tmp_path)
    )
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _paths: [
            {"plan_id": "plan-1", "scope": "policy", "unique_locators_count": 900}
        ],
    )
    monkeypatch.setattr(operator, "cmd_expand", lambda args: pytest.fail("expanded"))

    def answers(prompt: str, default: str = "") -> str:
        if "Parent plan" in prompt:
            return "1"
        return "10"

    monkeypatch.setattr(operator, "prompt_text", answers)

    operator._action_expand()
    assert "contraction" in capsys.readouterr().out


def test_catalog_selection_prefers_the_published_pointer(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A blank answer keeps ``current``; the listing makes the alternative visible."""
    monkeypatch.setattr(
        operator,
        "discover_catalogs",
        lambda _paths: [
            {"catalog_id": "cat-a", "target_row_count": 10, "part_count": 1},
            {"catalog_id": "cat-b", "target_row_count": 20, "part_count": 2},
        ],
    )
    monkeypatch.setattr(operator, "current_catalog_id", lambda _paths: "cat-b")
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: default)

    assert operator._ask_catalog("") == "cat-b"
    out = capsys.readouterr().out
    assert "cat-a" in out and "cat-b [current]" in out
    assert "20,000" not in out


def test_a_catalog_can_still_be_chosen_by_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operator,
        "discover_catalogs",
        lambda _paths: [
            {"catalog_id": "cat-a", "target_row_count": 10, "part_count": 1},
            {"catalog_id": "cat-b", "target_row_count": 20, "part_count": 2},
        ],
    )
    monkeypatch.setattr(operator, "current_catalog_id", lambda _paths: "cat-b")
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: "1")
    assert operator._ask_catalog("") == "cat-a"


def test_an_invalid_catalog_number_falls_back_to_current(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        operator,
        "discover_catalogs",
        lambda _paths: [
            {"catalog_id": "cat-a", "target_row_count": 1, "part_count": 1}
        ],
    )
    monkeypatch.setattr(operator, "current_catalog_id", lambda _paths: "cat-a")
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: "nope")
    assert operator._ask_catalog("") == "current"
    assert "invalid selection" in capsys.readouterr().out


def test_no_catalogs_published_falls_back_to_the_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operator, "discover_catalogs", lambda _paths: [])
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default: default)
    assert operator._ask_catalog("") == "current"


def _paths(tmp_path: Any):
    from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths

    return resolve_filing_catalog_paths(tmp_path)
