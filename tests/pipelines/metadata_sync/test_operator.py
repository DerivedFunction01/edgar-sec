"""Operator wizard menu and command-delegation tests.

The wizard is a thin presentation layer over the same command functions the CLI
uses. The failure this guards against is a binding that drifts from the command
surface: an action pointing at a command that no longer reads an argument the
wizard sets would fail only at runtime, inside an interactive session nobody is
running in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync import operator as operator_module
from edgar_sec.pipelines.metadata_sync.cli import (
    cmd_augment,
    cmd_compare,
    cmd_export,
    cmd_merge,
    cmd_plan,
    cmd_refresh,
    cmd_run,
    cmd_status,
    cmd_worker,
)
from edgar_sec.pipelines.metadata_sync.operator import (
    DEFAULT_INPUT,
    MENU_TITLE,
    _ask_int,
    _ask_plan_options,
    _ask_run_options,
    build_operator_menu,
    main,
)
from tests.support import fixture_path

COMMANDS = {
    "_action_plan": cmd_plan,
    "_action_status": cmd_status,
    "_action_run": cmd_run,
    "_action_merge": cmd_merge,
    "_action_augment": cmd_augment,
    "_action_export": cmd_export,
    "_action_worker": cmd_worker,
    "_action_refresh": cmd_refresh,
    "_action_compare": cmd_compare,
}


def test_menu_covers_the_whole_lifecycle() -> None:
    menu = build_operator_menu()
    assert [action.key for action in menu] == [str(n) for n in range(1, 10)]
    assert [action.callback.__name__ for action in menu] == list(COMMANDS)


def test_menu_actions_delegate_to_the_shared_command_functions() -> None:
    for action in build_operator_menu():
        assert action.callback.__name__ in COMMANDS


def test_menu_labels_describe_the_phase() -> None:
    labels = [action.label for action in menu_labels()]
    assert any("Plan" in label for label in labels)
    assert any("Merge" in label for label in labels)
    assert any("Augment" in label for label in labels)
    assert MENU_TITLE.startswith("Metadata Sync")


def menu_labels():
    return build_operator_menu()


def test_blank_numeric_answers_defer_to_the_settings_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    assert _ask_int("anything") is None
    assert _ask_int("anything", 7) is None


def test_an_unparsable_answer_falls_back_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "abc")
    assert _ask_int("anything", 7) is None
    assert "not a whole number" in capsys.readouterr().out


def test_ask_plan_options_returns_none_on_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    assert _ask_plan_options(with_limit=True) is None


def test_ask_plan_options_uses_registered_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "17")
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: default)
    options = _ask_plan_options()
    assert options is not None
    assert options.input_path is not None
    assert options.input_path.name == Path(DEFAULT_INPUT).name
    assert options.chunk_size == 17


def test_ask_plan_options_records_a_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter([str(fixture_path("cik_sec_mini.csv")), "1000", "3"])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    options = _ask_plan_options(with_limit=True)
    assert options is not None
    assert options.limit == 3


def test_ask_run_options_returns_none_without_a_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    assert _ask_run_options() is None


def test_ask_run_options_carries_an_explicit_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(["0123456789abcdef", ""])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    options = _ask_run_options()
    assert options is not None
    assert options.plan_id == "0123456789abcdef"
    assert options.bundle_root is None


def test_ask_run_options_reads_the_plan_id_from_a_copied_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker should not have to be told the plan it is already holding."""
    bundle = tmp_path / "worker-00"
    bundle.mkdir()
    (bundle / "plan.json").write_text(
        json.dumps({"plan_id": "0123456789abcdef"}), encoding="utf-8"
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    assert _ask_run_options(with_bundle=True) is None

    answers = iter([str(bundle), "", ""])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    options = _ask_run_options(with_bundle=True)
    assert options is not None
    assert options.plan_id == "0123456789abcdef"
    assert options.bundle_root == bundle.resolve()


def test_action_plan_delegates_to_cmd_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.pipelines.metadata_sync.options import plan_options

    monkeypatch.setattr(
        operator_module,
        "_ask_plan_options",
        lambda **_kwargs: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"), artifacts_root=tmp_path
        ),
    )
    called: list[object] = []
    monkeypatch.setattr(
        operator_module, "cmd_plan", lambda options: called.append(options)
    )
    operator_module._action_plan()
    assert len(called) == 1
    assert called[0].input_path is not None


def test_action_status_delegates_to_cmd_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.pipelines.metadata_sync.options import run_options

    monkeypatch.setattr(
        operator_module,
        "_ask_run_options",
        lambda **_kwargs: run_options(plan_id="p", artifacts_root=tmp_path),
    )
    called: list[object] = []
    monkeypatch.setattr(
        operator_module, "cmd_status", lambda options: called.append(options)
    )
    operator_module._action_status()
    assert len(called) == 1


def test_action_run_forwards_a_chunk_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.pipelines.metadata_sync.options import run_options

    monkeypatch.setattr(
        operator_module,
        "_ask_run_options",
        lambda **_kwargs: run_options(plan_id="p", artifacts_root=tmp_path),
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "0,2")
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_run", seen.append)
    operator_module._action_run()
    assert seen[0].chunk_ids == (0, 2)


def test_action_run_leaves_the_selection_empty_when_blank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.pipelines.metadata_sync.options import run_options

    monkeypatch.setattr(
        operator_module,
        "_ask_run_options",
        lambda **_kwargs: run_options(plan_id="p", artifacts_root=tmp_path),
    )
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_run", seen.append)
    operator_module._action_run()
    assert seen[0].chunk_ids == ()


def test_action_merge_delegates_to_cmd_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.pipelines.metadata_sync.options import run_options

    monkeypatch.setattr(
        operator_module,
        "_ask_run_options",
        lambda **_kwargs: run_options(plan_id="p", artifacts_root=tmp_path),
    )
    seen: list[object] = []
    monkeypatch.setattr(
        operator_module, "cmd_merge", lambda options: seen.append(options)
    )
    operator_module._action_merge()
    assert len(seen) == 1


def test_action_augment_requires_both_snapshot_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar_sec.pipelines.metadata_sync.options import plan_options

    monkeypatch.setattr(
        operator_module,
        "_ask_plan_options",
        lambda **_kwargs: plan_options(
            input_path=fixture_path("cik_sec_mini.csv"), artifacts_root=tmp_path
        ),
    )
    seen: list[dict] = []
    monkeypatch.setattr(
        operator_module,
        "cmd_augment",
        lambda options, **kwargs: seen.append(kwargs),
    )

    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    operator_module._action_augment()
    assert seen == []

    answers = iter(["base", "next", ""])
    monkeypatch.setattr(
        operator_module, "prompt_text", lambda label, default: next(answers)
    )
    operator_module._action_augment()
    assert seen[0]["base_snapshot_id"] == "base"
    assert seen[0]["new_snapshot_id"] == "next"


def test_cancelled_answers_short_circuit_every_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operator_module, "_ask_plan_options", lambda **_kwargs: None)
    monkeypatch.setattr(operator_module, "_ask_run_options", lambda **_kwargs: None)
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    called: list[object] = []
    for name, command in COMMANDS.items():
        monkeypatch.setattr(
            operator_module,
            command.__name__,
            lambda *a, _n=name, **k: called.append(_n),
        )
    for name in (
        "_action_plan",
        "_action_status",
        "_action_run",
        "_action_merge",
        "_action_augment",
        "_action_export",
        "_action_worker",
        "_action_compare",
    ):
        getattr(operator_module, name)()
        assert called == [], name


def test_refresh_needs_no_reference_and_still_reaches_the_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refreshing is not scoped to a plan, so a blank answer is not a cancel."""
    monkeypatch.setattr(operator_module, "prompt_text", lambda label, default: "")
    seen: list[object] = []
    monkeypatch.setattr(operator_module, "cmd_refresh", lambda root: seen.append(root))
    operator_module._action_refresh()
    assert seen == [None]


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
    assert "plan_id" in capsys.readouterr().out


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
    assert len(seen["menu"]) == len(COMMANDS)
    assert seen["exit_key"] == "0"


def test_main_delegates_a_command_to_the_cli(monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(
        operator_module, "cli_main", lambda argv: seen.append(argv) or 0
    )
    assert main(["status", "--plan-id", "p"]) == 0
    assert seen == [["status", "--plan-id", "p"]]
