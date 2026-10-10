from __future__ import annotations

from edgar_sec.pipelines.document_acquisition import operator


def _menu_action(label_fragment: str):
    return next(
        action
        for action in operator.build_operator_menu()
        if label_fragment in action.label
    )


def test_project_action_delegates_to_cli(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default="": "plan-1")
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Project an S6").callback()

    assert calls == [["project", "--plan-id", "plan-1"]]


def test_status_action_delegates_selected_run_to_cli(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator, "prompt_text", lambda prompt, default="": "run-1")
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Inspect acquisition runs").callback()

    assert calls == [["status", "--run-id", "run-1"]]


def test_run_defaults_to_no_network(monkeypatch, capsys) -> None:
    responses = iter(("run-1", "4096", "no", "no"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda prompt, default="": next(responses),
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Run acquisition").callback()

    assert calls == []
    assert "no network request was made" in capsys.readouterr().out


def test_run_confirms_network_and_passes_retry_and_byte_limit(monkeypatch) -> None:
    responses = iter(("run-1", "4096", "yes", "yes"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda prompt, default="": next(responses),
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Run acquisition").callback()

    assert calls == [
        [
            "run",
            "--run-id",
            "run-1",
            "--max-response-bytes",
            "4096",
            "--retry-failures",
        ]
    ]


def test_run_refuses_invalid_byte_limit_before_network_prompt(monkeypatch) -> None:
    responses = iter(("run-1", "unbounded"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda prompt, default="": next(responses),
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Run acquisition").callback()

    assert calls == []
