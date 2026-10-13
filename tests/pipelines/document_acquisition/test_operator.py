from __future__ import annotations

from edgar_sec.pipelines.document_acquisition import operator


def _menu_action(label_fragment: str):
    return next(
        action
        for action in (
            *operator.build_operator_menu(),
            *operator._build_snapshot_menu(),
            *operator._build_fixture_review_menu(),
        )
        if label_fragment in action.label
    )


def test_menu_groups_fixture_review_actions_like_inventory_consoles(monkeypatch):
    menu = operator.build_operator_menu()
    assert [action.key for action in menu] == ["1", "2", "3", "4", "p", "f"]
    assert "Snapshot console" in menu[4].label
    assert "Fixtures and review console" in menu[5].label

    opened = []
    monkeypatch.setattr(
        operator,
        "run_interactive_menu",
        lambda title, actions, **kwargs: opened.append((title, actions, kwargs)) or 0,
    )
    menu[4].callback()
    menu[5].callback()

    snapshot_title, snapshot_actions, snapshot_kwargs = opened[0]
    assert snapshot_title == "Document Acquisition Snapshot Console"
    assert [action.key for action in snapshot_actions] == ["1", "2"]
    assert [action.label for action in snapshot_actions] == [
        "Publish snapshot (S11 gate)",
        "Snapshot status (S11 gate)",
    ]
    assert snapshot_kwargs == {}

    fixture_title, fixture_actions, fixture_kwargs = opened[1]
    assert fixture_title == "Document Acquisition Fixtures & Review Console"
    assert [action.key for action in fixture_actions] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
    ]
    assert [action.label for action in fixture_actions] == [
        "Create local fixture",
        "Fill local fixture evidence (confirmation required)",
        "List local fixtures",
        "Replay local fixture (confirmation required)",
        "Generate review artifacts",
        "Compare review runs",
        "Audit acquisition evidence (S9/S10; not implemented)",
    ]
    assert fixture_kwargs == {}


def test_evidence_audit_action_remains_fail_closed(capsys):
    _menu_action("Audit acquisition evidence").callback()

    message = capsys.readouterr().err
    assert "not implemented: S9/S10 evidence audit" in message
    assert "no acquisition evidence was read or written" in message


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


def test_process_defaults_retry_to_no_and_routes_through_cli(monkeypatch) -> None:
    responses = iter((" run-1 ", ""))
    prompts = []
    calls: list[list[str]] = []

    def prompt(message: str, default: str = "") -> str:
        prompts.append((message, default))
        return next(responses) or default

    monkeypatch.setattr(operator, "prompt_text", prompt)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Process acquired bodies").callback()

    assert prompts == [
        ("Acquisition run ID", ""),
        ("Retry failed processing targets? (yes/no)", "no"),
    ]
    assert calls == [["process", "--run-id", "run-1"]]


def test_process_retry_confirmation_routes_option_through_cli(monkeypatch) -> None:
    responses = iter(("run-1", "yes"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator, "prompt_text", lambda prompt, default="": next(responses)
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Process acquired bodies").callback()

    assert calls == [["process", "--run-id", "run-1", "--retry-failures"]]


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

    assert calls == [["fixture", "create", "--fixture", "fixture-1"]]


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

    _menu_action("Fill local fixture evidence (confirmation required)").callback()

    assert calls == [
        [
            "fixture",
            "fill",
            "--fixture",
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
        _menu_action("Fill local fixture evidence (confirmation required)").callback()

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
            "--fixture",
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
            "--fixture",
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


def test_review_generate_passes_shared_console_filters(monkeypatch) -> None:
    answers = iter(("fixture-1", "capture-1", "target-1", "review-output"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda prompt, default="": next(answers),
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Generate review artifacts").callback()

    assert calls == [
        [
            "review",
            "generate",
            "--fixture",
            "fixture-1",
            "--capture-id",
            "capture-1",
            "--target-id",
            "target-1",
            "--output",
            "review-output",
        ]
    ]


def test_review_compare_passes_shared_console_run_paths(monkeypatch) -> None:
    answers = iter(("base-run", "new-run"))
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda prompt, default="": next(answers),
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Compare review runs").callback()

    assert calls == [["review", "compare", "--base", "base-run", "--new", "new-run"]]
