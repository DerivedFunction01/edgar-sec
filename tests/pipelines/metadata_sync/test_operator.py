"""Operator wizard menu and command-delegation tests.

The wizard is a thin presentation layer over the same command functions the CLI
uses. The failure this guards against is a binding that drifts from the command
surface: an action pointing at a command that no longer reads an argument the
wizard sets would fail only at runtime, inside an interactive session nobody is
running in CI.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync import operator as operator_module
from edgar_sec.pipelines.metadata_sync.cli import (
    cmd_augment,
    cmd_merge,
    cmd_plan,
    cmd_run,
    cmd_status,
)
from edgar_sec.pipelines.metadata_sync.operator import (
    DEFAULT_INPUT,
    MENU_TITLE,
    _ask_configuration,
    _namespace,
    build_operator_menu,
    main,
)
from tests.support import fixture_path


def test_menu_binds_every_action_to_a_command() -> None:
    menu = build_operator_menu()
    assert [action.key for action in menu] == ["1", "2", "3", "4", "5"]
    assert [action.callback.__name__ for action in menu] == [
        "_action_plan",
        "_action_status",
        "_action_run",
        "_action_merge",
        "_action_augment",
    ]


def test_menu_actions_delegate_to_the_shared_command_functions() -> None:
    targets = {
        "_action_plan": cmd_plan,
        "_action_status": cmd_status,
        "_action_run": cmd_run,
        "_action_merge": cmd_merge,
        "_action_augment": cmd_augment,
    }
    for action in build_operator_menu():
        assert action.callback.__name__ in targets


def test_menu_labels_describe_the_phase() -> None:
    labels = [action.label for action in build_operator_menu()]
    assert any("Plan" in label for label in labels)
    assert any("Merge" in label for label in labels)
    assert MENU_TITLE.startswith("Metadata Sync")


def test_namespace_matches_the_parser_shape() -> None:
    """Every field the command functions read must exist on the namespace."""
    namespace = _namespace("ciks.csv", "5", "2", "3")
    assert namespace.input == "ciks.csv"
    assert (namespace.chunk_size, namespace.partition_count, namespace.workers) == (
        5,
        2,
        3,
    )
    assert namespace.chunk is None
    assert namespace.partition is None
    assert namespace.limit is None
    for field in ("input", "artifacts", "chunk_size", "partition_count", "workers"):
        assert isinstance(getattr(namespace, field), object)
    # The removed merge-only override must not linger in the wizard namespace.
    assert not hasattr(namespace, "snapshot_id")


def test_blank_numeric_answers_defer_to_the_settings_registry() -> None:
    namespace = _namespace("ciks.csv", "", "", "")
    assert namespace.chunk_size is None
    assert namespace.partition_count is None
    assert namespace.workers is None


def test_ask_configuration_prompts_for_the_required_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def fake_prompt(label: str, default: str) -> str:
        prompts.append(label)
        return "" if label == "Input CIK manifest" else default

    monkeypatch.setattr(operator_module, "prompt_text", fake_prompt)
    assert _ask_configuration() is None
    assert prompts == ["Input CIK manifest"]


def test_ask_configuration_uses_registered_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "17")
    monkeypatch.setenv("RUNTIME_PARTITION_COUNT", "4")
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    values = _ask_configuration()
    assert values is not None
    assert values[0] == DEFAULT_INPUT
    assert values[1] == "17"
    assert values[2] == "4"


def test_action_plan_delegates_to_cmd_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        operator_module,
        "_ask_configuration",
        lambda: (str(fixture_path("cik_sec_mini.csv")), "", "", ""),
    )
    called: list[str] = []
    monkeypatch.setattr(
        operator_module, "cmd_plan", lambda args: called.append(args.command)
    )
    operator_module._action_plan()
    assert called == ["plan"]


def test_action_status_delegates_to_cmd_status(monkeypatch) -> None:
    monkeypatch.setattr(
        operator_module, "_ask_configuration", lambda: ("ciks.csv", "", "", "")
    )
    called: list[str] = []
    monkeypatch.setattr(
        operator_module, "cmd_status", lambda args: called.append(args.command)
    )
    operator_module._action_status()
    assert called == ["status"]


def test_action_run_forwards_chunk_and_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operator_module, "_ask_configuration", lambda: ("ciks.csv", "", "", "")
    )
    answers = iter(["4", "1"])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    seen: list[argparse.Namespace] = []
    monkeypatch.setattr(operator_module, "cmd_run", seen.append)
    operator_module._action_run()
    assert seen[0].chunk == 4
    assert seen[0].partition == 1
    assert seen[0].command == "run"


def test_action_run_leaves_selectors_none_when_blank(monkeypatch) -> None:
    monkeypatch.setattr(
        operator_module, "_ask_configuration", lambda: ("ciks.csv", "", "", "")
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    seen: list[argparse.Namespace] = []
    monkeypatch.setattr(operator_module, "cmd_run", seen.append)
    operator_module._action_run()
    assert seen[0].chunk is None
    assert seen[0].partition is None


def test_action_merge_delegates_to_cmd_merge(monkeypatch) -> None:
    monkeypatch.setattr(
        operator_module, "_ask_configuration", lambda: ("ciks.csv", "", "", "")
    )
    seen: list[str] = []
    monkeypatch.setattr(
        operator_module, "cmd_merge", lambda args: seen.append(args.command)
    )
    operator_module._action_merge()
    assert seen == ["merge"]


def test_action_augment_requires_both_snapshot_ids(monkeypatch) -> None:
    monkeypatch.setattr(
        operator_module, "_ask_configuration", lambda: ("ciks.csv", "", "", "")
    )
    seen: list[argparse.Namespace] = []
    monkeypatch.setattr(operator_module, "cmd_augment", seen.append)

    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    operator_module._action_augment()
    assert seen == []

    answers = iter(["base", "next"])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    operator_module._action_augment()
    assert seen[0].base_snapshot_id == "base"
    assert seen[0].new_snapshot_id == "next"


def test_cancelled_configuration_short_circuits_every_action(monkeypatch) -> None:
    monkeypatch.setattr(operator_module, "_ask_configuration", lambda: None)
    called: list[object] = []
    for command in ("cmd_plan", "cmd_status", "cmd_run", "cmd_merge", "cmd_augment"):
        monkeypatch.setattr(
            operator_module, command, lambda args, sink=called: sink.append(args)
        )
    for name in (
        "_action_plan",
        "_action_status",
        "_action_run",
        "_action_merge",
        "_action_augment",
    ):
        getattr(operator_module, name)()
        assert called == [], name


def test_main_dispatches_a_command_argument_to_the_cli(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "plan",
            "--input",
            str(fixture_path("cik_sec_mini.csv")),
            "--artifacts",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    assert "written" in capsys.readouterr().out


def test_main_uses_the_interactive_menu_when_no_command_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        operator_module,
        "run_interactive_menu",
        lambda title, menu, exit_key="0": (
            seen.update(title=title, menu=menu, exit_key=exit_key) or 0
        ),
    )
    assert main([]) == 0
    assert seen["title"] == MENU_TITLE
    assert len(seen["menu"]) == 5
    assert seen["exit_key"] == "0"


def test_main_delegates_a_command_to_the_cli(monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(
        operator_module, "cli_main", lambda argv: seen.append(argv) or 0
    )
    assert main(["status", "--input", "x.csv"]) == 0
    assert seen == [["status", "--input", "x.csv"]]
