from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import edgar_sec.pipelines.document_inventory.operator as operator


def test_menu_exposes_discovered_fixture_operations() -> None:
    actions = operator.build_operator_menu()
    assert [action.key for action in actions] == ["1", "2", "3", "4", "5", "6"]
    assert "catalog plan" in actions[0].label
    assert "List discovered fixtures" == actions[2].label
    assert "DAG" in actions[5].label


def test_create_uses_discovered_plan_and_confirmed_cli_function(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[Namespace] = []
    monkeypatch.setattr(operator, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _root: [{"plan_id": "plan-1", "catalog_id": "c"}],
    )
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "fixture-1")
    monkeypatch.setattr(operator, "_confirm_capture", lambda *_args: True)
    monkeypatch.setattr(operator, "cmd_fixture_create", calls.append)

    operator._action_create()

    assert len(calls) == 1
    assert calls[0].fixture == "fixture-1"
    assert calls[0].catalog_plan == "plan-1"
    assert calls[0].artifacts == ""


def test_fill_discovers_both_fixture_and_plan(tmp_path: Path, monkeypatch) -> None:
    calls: list[Namespace] = []
    monkeypatch.setattr(operator, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        operator, "discover_fixtures", lambda _root: [{"fixture_id": "fixture-1"}]
    )
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _root: [{"plan_id": "plan-1", "catalog_id": "c"}],
    )
    monkeypatch.setattr(operator, "_confirm_capture", lambda *_args: True)
    monkeypatch.setattr(operator, "cmd_fixture_fill", calls.append)

    operator._action_fill()

    assert len(calls) == 1
    assert calls[0].fixture == "fixture-1"
    assert calls[0].catalog_plan == "plan-1"


def test_create_cancels_without_confirmation(tmp_path: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(operator, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        operator, "discover_plans", lambda _root: [{"plan_id": "p", "catalog_id": "c"}]
    )
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "f")
    monkeypatch.setattr(operator, "_confirm_capture", lambda *_args: False)
    monkeypatch.setattr(operator, "cmd_fixture_create", calls.append)
    operator._action_create()
    assert calls == []


def test_operator_dispatches_cli_arguments(monkeypatch) -> None:
    captured = []

    def dispatch(title, menu, cli_main, argv):
        captured.append((title, menu, cli_main, argv))
        return 17

    monkeypatch.setattr(operator, "operator_entrypoint", dispatch)
    assert operator.main(["fixture", "list"]) == 17
    title, menu, cli_main, argv = captured[0]
    assert title == operator.MENU_TITLE
    assert menu == operator.build_operator_menu()
    assert argv == ["fixture", "list"]
    assert cli_main is operator.cli_main
