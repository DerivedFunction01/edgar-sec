from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from edgar_sec.pipelines.document_acquisition import operator
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths


def _menu_action(label_fragment: str):
    return next(
        action
        for action in operator.build_operator_menu()
        if label_fragment in action.label
    )


def _active_plan(plan_id="plan-a"):
    return SimpleNamespace(
        plan_id=plan_id,
        manifest={
            "plan_digest": "a" * 64,
            "target_row_count": 3,
            "target_schema_version": 1,
        },
    )


def _console(tmp_path):
    return operator._FixtureReviewConsole(tmp_path)


def test_menu_routes_fixture_review_to_shared_console(monkeypatch):
    menu = operator.build_operator_menu()
    assert [action.key for action in menu] == ["1", "2", "3", "p", "f"]
    assert "Snapshot DAG console" in menu[3].label
    assert "Fixtures and review console" in menu[4].label

    from edgar_sec.infra.storage.review import operator as review_operator

    opened = []
    monkeypatch.setattr(
        review_operator,
        "run_review_menu",
        lambda config: opened.append(config) or 0,
    )
    _menu_action("Fixtures and review console").callback()

    config = opened[0]
    assert config.title == "Document Acquisition Fixtures & Review Console"
    assert config.prompt_limit is False
    assert config.prompt_output is False
    assert config.prompt_workers is False
    assert config.require_active_plan is True
    assert callable(config.plan_discovery)
    assert callable(config.fixture_filter)
    assert callable(config.fill_action)


def test_menu_routes_snapshot_console_to_shared_dag_console(monkeypatch):
    from edgar_sec.infra.storage.dag import menu as dag_menu

    opened = []
    monkeypatch.setattr(
        dag_menu,
        "run_dag_menu",
        lambda config: opened.append(config) or 0,
    )

    _menu_action("Snapshot DAG console").callback()

    config = opened[0]
    assert config.title == "Document Acquisition Snapshot DAG Console"
    assert config.publish_action is operator._action_publish_run
    assert callable(config.snapshots_root)


def test_project_action_delegates_to_cli(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        operator, "_select_target_plan", lambda: SimpleNamespace(plan_id="plan-1")
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Project a target plan").callback()

    assert calls == [["project", "--plan-id", "plan-1"]]


def test_status_action_uses_paginated_run_and_target_choices(monkeypatch) -> None:
    calls = []
    run_items = [
        operator.PickItem("all", "All acquisition runs", ""),
        operator.PickItem("run-1", "run-1", "run-1"),
    ]
    target_items = [
        operator.PickItem("summary", "Run summary", ""),
        operator.PickItem("target-1", "target-1", "target-1"),
    ]
    prompts = []

    def choose(items, *, prompt_label):
        prompts.append(prompt_label)
        return run_items[1] if prompt_label == "Acquisition run" else target_items[1]

    monkeypatch.setattr(operator, "_run_items", lambda **_kwargs: run_items)
    monkeypatch.setattr(operator, "_target_items", lambda _run_id: target_items)
    monkeypatch.setattr(operator, "prompt_paginated_choice", choose)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Inspect acquisition runs").callback()

    assert prompts == ["Acquisition run", "Target status"]
    assert calls == [["status", "--run-id", "run-1", "--target-id", "target-1"]]


def test_status_action_handles_no_runs_without_opening_a_database(
    tmp_path, monkeypatch, capsys
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    monkeypatch.setattr(operator, "resolve_acquisition_paths", lambda: paths)
    monkeypatch.setattr(
        operator, "cli_main", lambda _args: pytest.fail("status should not run")
    )

    operator._action_status()

    assert "No acquisition runs found." in capsys.readouterr().out


def test_run_items_discover_safe_runs_in_sorted_order(tmp_path, monkeypatch) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    paths.run_dir("run-b").mkdir(parents=True)
    paths.run_dir("run-a").mkdir()
    monkeypatch.setattr(operator, "resolve_acquisition_paths", lambda: paths)

    assert [item.value for item in operator._run_items()] == ["run-a", "run-b"]


def test_run_action_uses_paged_run_choice(monkeypatch) -> None:
    calls = []
    confirms = iter((False, False, True))
    monkeypatch.setattr(operator, "_choose_run_id", lambda _prompt: "run-1")
    monkeypatch.setattr(operator, "_configured_response_byte_limit", lambda: 1024)
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "4096")
    monkeypatch.setattr(
        operator, "prompt_confirm", lambda *_args, **_kw: next(confirms)
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    operator._action_run()

    assert calls == [["run", "--run-id", "run-1", "--max-response-bytes", "4096"]]


def test_console_discovers_only_fully_validated_s6_plans(tmp_path, monkeypatch) -> None:
    console = _console(tmp_path)
    discoveries = [
        SimpleNamespace(plan_id="plan-a", plan=object()),
        SimpleNamespace(plan_id="plan-b", plan=object()),
        SimpleNamespace(plan_id="invalid", plan=None),
    ]
    validated = _active_plan("plan-a")
    monkeypatch.setattr(operator, "discover_document_plans", lambda _paths: discoveries)
    monkeypatch.setattr(
        operator,
        "read_published_plan",
        lambda plan_id, _paths: (
            validated
            if plan_id == "plan-a"
            else (_ for _ in ()).throw(ValueError("invalid target plan"))
        ),
    )

    assert console.plans() == [validated]
    assert console.plan_items()[0].value["plan_id"] == "plan-a"
    assert console.plan_summary(None) == "Active S6 target plan: none"
    assert console.plan_summary(console.plan_items()[0].value).startswith(
        "Active S6 target plan: plan-a"
    )


def test_fixture_filter_uses_exact_target_plan_pin(tmp_path) -> None:
    console = _console(tmp_path)
    plan = {
        "plan_id": "plan-a",
        "plan_digest": "a" * 64,
        "target_plan_schema_version": 1,
    }
    assert console.fixture_matches_plan(
        {
            "target_plan_id": "plan-a",
            "target_plan_digest": "a" * 64,
            "target_plan_schema_version": 1,
        },
        plan,
    )
    assert not console.fixture_matches_plan(
        {
            "target_plan_id": "plan-a",
            "target_plan_digest": "b" * 64,
            "target_plan_schema_version": 1,
        },
        plan,
    )


def test_fixture_fill_confirms_direct_plan_fetch_and_bounds_targets(
    tmp_path, monkeypatch
) -> None:
    console = _console(tmp_path)
    plan = {"plan_id": "plan-a", "selected_rows": 1174}
    calls = []
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "25")
    monkeypatch.setattr(operator, "prompt_confirm", lambda *_args, **_kw: True)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    assert console.fill_fixture("fixture-a", plan, None, tmp_path)

    assert calls == [
        [
            "fixture",
            "fill",
            "--fixture",
            "fixture-a",
            "--plan-id",
            "plan-a",
            "--allow-network",
            "--artifacts",
            str(tmp_path),
            "--limit",
            "25",
        ]
    ]


def test_fixture_fill_cancelled_before_network_does_not_call_cli(
    tmp_path, monkeypatch
) -> None:
    console = _console(tmp_path)
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "25")
    monkeypatch.setattr(operator, "prompt_confirm", lambda *_args, **_kw: False)
    monkeypatch.setattr(
        operator, "cli_main", lambda _args: pytest.fail("cancelled fill ran")
    )

    assert not console.fill_fixture(
        "fixture-a", {"plan_id": "plan-a", "selected_rows": 1174}, None, tmp_path
    )


def test_console_analyzes_selected_review_runs_offline(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _console(tmp_path).analyze_reviews(("review-a", "review-b"))

    assert calls == [
        [
            "review",
            "analyze",
            "--run",
            "review-a",
            "--run",
            "review-b",
            "--artifacts",
            str(tmp_path),
        ]
    ]


def test_operator_has_no_separate_processing_lifecycle_entry() -> None:
    assert all(
        "Process acquired bodies" not in action.label
        for action in operator.build_operator_menu()
    )


def test_operator_exposes_one_fixture_review_console_without_export_action() -> None:
    labels = [item.label for item in operator.build_operator_menu()]

    assert any("Fixtures and review console" in label for label in labels)
    assert not any("Replay local fixture" in label for label in labels)
    assert not any("Create local fixture" in label for label in labels)


def test_publish_action_requires_confirmation_and_dispatches_selected_run(
    tmp_path, monkeypatch
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    choices = iter((operator.PickItem("run-1", "run-1", "run-1"),))
    calls = []
    confirms = iter((True,))
    monkeypatch.setattr(operator, "resolve_acquisition_paths", lambda: paths)
    monkeypatch.setattr(operator, "discover_run_ids", lambda _paths: ["run-1"])
    monkeypatch.setattr(
        operator, "prompt_paginated_choice", lambda *_args, **_kwargs: next(choices)
    )
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "main")
    monkeypatch.setattr(
        operator, "prompt_confirm", lambda *_args, **_kwargs: next(confirms)
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    operator._action_publish_run()

    assert calls == [
        [
            "publish",
            "--run-id",
            "run-1",
            "--branch",
            "main",
            "--artifacts",
            str(tmp_path),
        ]
    ]


def test_publish_action_cancellation_does_not_dispatch(tmp_path, monkeypatch, capsys):
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    monkeypatch.setattr(operator, "resolve_acquisition_paths", lambda: paths)
    monkeypatch.setattr(operator, "discover_run_ids", lambda _paths: ["run-1"])
    monkeypatch.setattr(
        operator,
        "prompt_paginated_choice",
        lambda *_args, **_kwargs: operator.PickItem("run-1", "run-1", "run-1"),
    )
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "main")
    monkeypatch.setattr(operator, "prompt_confirm", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        operator, "cli_main", lambda _args: pytest.fail("cancelled publish ran")
    )

    operator._action_publish_run()

    assert "Publication cancelled" in capsys.readouterr().out
