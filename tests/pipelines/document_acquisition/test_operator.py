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

    _menu_action("Project a target plan").callback()

    assert calls == [["project", "--plan-id", "plan-1"]]


def test_status_action_delegates_selected_run_to_cli(monkeypatch) -> None:
    calls: list[list[str]] = []
    responses = iter(("run-1", ""))
    monkeypatch.setattr(
        operator, "prompt_text", lambda prompt, default="": next(responses)
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Inspect acquisition runs").callback()

    assert calls == [["status", "--run-id", "run-1"]]


def test_status_action_prompts_for_target_only_after_run_and_delegates(monkeypatch):
    responses = iter(("run-1", "target-1"))
    prompts = []
    calls: list[list[str]] = []

    def prompt(message: str, default: str = "") -> str:
        prompts.append(message)
        return next(responses)

    monkeypatch.setattr(operator, "prompt_text", prompt)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Inspect acquisition runs").callback()

    assert prompts == ["Run ID (blank lists all runs)", "Target ID (optional)"]
    assert calls == [["status", "--run-id", "run-1", "--target-id", "target-1"]]


def test_status_action_does_not_prompt_for_target_when_listing_runs(monkeypatch):
    prompts = []
    calls: list[list[str]] = []

    def prompt(message: str, default: str = "") -> str:
        prompts.append(message)
        return ""

    monkeypatch.setattr(operator, "prompt_text", prompt)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Inspect acquisition runs").callback()

    assert prompts == ["Run ID (blank lists all runs)"]
    assert calls == [["status"]]


def test_run_defaults_to_no_network(monkeypatch, capsys) -> None:
    responses = iter(("run-1", "", "no", "", "no"))
    calls: list[list[str]] = []
    defaults: list[str] = []

    def prompt(prompt: str, default: str = "") -> str:
        defaults.append(default)
        return next(responses)

    monkeypatch.setattr(
        operator,
        "resolve_settings",
        lambda *, include: {"acquisition.max_response_bytes": 268435456},
    )
    monkeypatch.setattr(operator, "prompt_text", prompt)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Run acquisition").callback()

    assert calls == []
    assert defaults == ["", "268435456", "no", "no", "no"]
    assert "no network request was made" in capsys.readouterr().out


def test_run_confirms_network_and_passes_retry_and_byte_limit(monkeypatch) -> None:
    responses = iter(("run-1", "4096", "yes", "yes", "yes"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "resolve_settings",
        lambda *, include: {"acquisition.max_response_bytes": 268435456},
    )
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
            "--retain-response-evidence",
        ]
    ]


def test_run_leaves_response_retention_off_by_default(monkeypatch) -> None:
    responses = iter(("run-1", "", "no", "", "yes"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "resolve_settings",
        lambda *, include: {"acquisition.max_response_bytes": 268435456},
    )
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
            "268435456",
        ]
    ]


def test_run_cancels_on_invalid_retention_answer_before_network_prompt(monkeypatch):
    responses = iter(("run-1", "", "no", "maybe"))
    calls: list[list[str]] = []
    defaults: list[str] = []
    monkeypatch.setattr(
        operator,
        "resolve_settings",
        lambda *, include: {"acquisition.max_response_bytes": 268435456},
    )

    def prompt(prompt: str, default: str = "") -> str:
        defaults.append(default)
        return next(responses)

    monkeypatch.setattr(operator, "prompt_text", prompt)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Run acquisition").callback()

    assert calls == []
    assert defaults == ["", "268435456", "no", "no"]


def test_run_refuses_invalid_byte_limit_before_network_prompt(monkeypatch) -> None:
    responses = iter(("run-1", "unbounded"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "resolve_settings",
        lambda *, include: {"acquisition.max_response_bytes": 268435456},
    )
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda prompt, default="": next(responses),
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Run acquisition").callback()

    assert calls == []


def test_fixture_create_requires_id_and_delegates_to_cli(monkeypatch) -> None:
    responses = iter((" fixture-1 ", ""))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda prompt, default="": next(responses),
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Create local fixture").callback()
    _menu_action("Create local fixture").callback()

    assert calls == [["fixture", "create", "--fixture-id", "fixture-1"]]


def test_fixture_capture_requires_ids_limit_and_confirmation(monkeypatch) -> None:
    responses = iter(("fixture-1", "run-1", "target-1", "attempt-1", "", "YES"))
    calls: list[list[str]] = []
    defaults: list[str] = []

    def prompt(prompt: str, default: str = "") -> str:
        defaults.append(default)
        return next(responses)

    monkeypatch.setattr(
        operator,
        "resolve_settings",
        lambda *, include: {"acquisition.max_response_bytes": 268435456},
    )
    monkeypatch.setattr(operator, "prompt_text", prompt)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Capture local fixture").callback()

    assert calls == [
        [
            "fixture",
            "capture",
            "--fixture-id",
            "fixture-1",
            "--run-id",
            "run-1",
            "--target-id",
            "target-1",
            "--attempt-id",
            "attempt-1",
            "--max-response-bytes",
            "268435456",
        ]
    ]
    assert defaults == ["", "", "", "", "268435456", "no"]


def test_fixture_capture_empty_id_invalid_limit_or_no_confirmation_does_no_work(
    monkeypatch,
) -> None:
    cases = (
        ("fixture-1", "", "target-1", "attempt-1", "4096"),
        ("fixture-1", "run-1", "target-1", "attempt-1", "0"),
        ("fixture-1", "run-1", "target-1", "attempt-1", "unbounded"),
        ("fixture-1", "run-1", "target-1", "attempt-1", "²"),
        ("fixture-1", "run-1", "target-1", "attempt-1", "4096", "no"),
        ("fixture-1", "run-1", "target-1", "attempt-1", "4096", "maybe"),
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "resolve_settings",
        lambda *, include: {"acquisition.max_response_bytes": 268435456},
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    for responses in cases:
        answers = iter(responses)
        monkeypatch.setattr(
            operator,
            "prompt_text",
            lambda prompt, default="": next(answers),
        )
        _menu_action("Capture local fixture").callback()

    assert calls == []


def test_fixture_list_passes_selected_optional_filters_without_confirmation(
    monkeypatch,
) -> None:
    responses = iter(("fixture-1", "", "target-1"))
    calls: list[list[str]] = []
    defaults: list[str] = []

    def prompt(prompt: str, default: str = "") -> str:
        defaults.append(default)
        return next(responses)

    monkeypatch.setattr(operator, "prompt_text", prompt)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("List local fixtures").callback()

    assert calls == [
        [
            "fixture",
            "list",
            "--fixture-id",
            "fixture-1",
            "--target-id",
            "target-1",
        ]
    ]
    assert defaults == ["", "", ""]


def test_fixture_list_empty_filters_lists_all_without_confirmation(monkeypatch) -> None:
    responses = iter(("", "", ""))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda prompt, default="": next(responses),
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("List local fixtures").callback()

    assert calls == [["fixture", "list"]]


def test_fixture_replay_requires_ids_path_and_write_confirmation(monkeypatch) -> None:
    responses = iter(("fixture-1", "capture-1", "target-1", "/tmp/replay.html", "yes"))
    calls: list[list[str]] = []
    defaults: list[str] = []

    def prompt(prompt: str, default: str = "") -> str:
        defaults.append(default)
        return next(responses)

    monkeypatch.setattr(operator, "prompt_text", prompt)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Replay local fixture").callback()

    assert calls == [
        [
            "fixture",
            "replay",
            "--fixture-id",
            "fixture-1",
            "--capture-id",
            "capture-1",
            "--target-id",
            "target-1",
            "--output",
            "/tmp/replay.html",
        ]
    ]
    assert defaults == ["", "", "", "", "no"]


def test_fixture_replay_empty_or_invalid_response_does_no_work(monkeypatch) -> None:
    cases = (
        ("fixture-1", "capture-1", "target-1", ""),
        ("fixture-1", "capture-1", "target-1", "/tmp/replay.html", "no"),
        ("fixture-1", "capture-1", "target-1", "/tmp/replay.html", "maybe"),
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    for responses in cases:
        answers = iter(responses)
        monkeypatch.setattr(
            operator,
            "prompt_text",
            lambda prompt, default="": next(answers),
        )
        _menu_action("Replay local fixture").callback()

    assert calls == []
