from __future__ import annotations

import json
from pathlib import Path
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


def test_menu_groups_fixture_review_actions_like_inventory_consoles(monkeypatch):
    menu = operator.build_operator_menu()
    assert [action.key for action in menu] == ["1", "2", "3", "p", "f"]
    assert "Snapshot console" in menu[3].label
    assert "Fixtures and review console" in menu[4].label

    opened = []
    monkeypatch.setattr(
        operator,
        "run_interactive_menu",
        lambda title, actions, **kwargs: opened.append((title, actions, kwargs)) or 0,
    )
    menu[3].callback()
    menu[4].callback()

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
        "Select or switch active S6 plan",
        "Create fixture for active S6 plan",
        "Fill fixture from recorded run evidence",
        "List fixtures deterministically",
        "Generate offline review artifacts",
        "Compare validated review runs",
        "Analyze review runs (offline)",
    ]
    assert callable(fixture_kwargs["before_menu"])


def test_project_action_delegates_to_cli(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "_select_target_plan",
        lambda: SimpleNamespace(plan_id="plan-1"),
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _menu_action("Project a target plan").callback()

    assert calls == [["project", "--plan-id", "plan-1"]]


def test_status_action_uses_paginated_run_and_target_choices(monkeypatch) -> None:
    calls: list[list[str]] = []
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


def test_run_discovery_uses_paginated_picker(monkeypatch) -> None:
    items = [
        operator.PickItem("run-a", "run-a", "run-a"),
        operator.PickItem("run-b", "run-b", "run-b"),
    ]
    prompts = []
    monkeypatch.setattr(operator, "_run_items", lambda **_kwargs: items)
    monkeypatch.setattr(
        operator,
        "prompt_paginated_choice",
        lambda choices, **kwargs: prompts.append(kwargs["prompt_label"]) or choices[1],
    )

    assert operator._choose_run_id("Projected run") == "run-b"
    assert prompts == ["Projected run"]


def test_run_items_discover_safe_runs_in_sorted_order(tmp_path, monkeypatch) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    paths.run_dir("run-b").mkdir(parents=True)
    paths.run_dir("run-a").mkdir()
    monkeypatch.setattr(operator, "resolve_acquisition_paths", lambda: paths)

    assert [item.value for item in operator._run_items()] == ["run-a", "run-b"]


def test_run_action_uses_paged_run_choice(monkeypatch) -> None:
    calls = []
    answers = iter(("4096", "no", "no", "yes"))
    monkeypatch.setattr(operator, "_choose_run_id", lambda _prompt: "run-1")
    monkeypatch.setattr(operator, "_configured_response_byte_limit", lambda: 1024)
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: next(answers))
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    operator._action_run()

    assert calls == [["run", "--run-id", "run-1", "--max-response-bytes", "4096"]]


def _active_plan(plan_id="plan-a"):
    return SimpleNamespace(
        plan_id=plan_id,
        manifest={
            "plan_digest": "a" * 64,
            "target_row_count": 3,
            "target_schema_version": 1,
        },
    )


def _console(tmp_path, plan_id="plan-a"):
    return operator._FixtureReviewConsole(tmp_path, _active_plan(plan_id))


def test_operator_exposes_one_fixture_review_console_without_export_action() -> None:
    labels = [item.label for item in operator.build_operator_menu()]

    assert any("Fixtures and review console" in label for label in labels)
    assert not any("Replay local fixture" in label for label in labels)
    assert not any("Create local fixture" in label for label in labels)


def test_console_switches_between_validated_published_plans(
    tmp_path, monkeypatch
) -> None:
    console = _console(tmp_path)
    plans = [_active_plan("plan-a"), _active_plan("plan-b")]
    monkeypatch.setattr(console, "plans", lambda: plans)
    monkeypatch.setattr(
        operator, "prompt_paginated_choice", lambda choices, **_kwargs: choices[1]
    )

    console.switch_plan()

    assert console.active_plan.plan_id == "plan-b"
    assert console.label().startswith("Active S6 target plan: plan-b")


def test_operator_has_no_separate_processing_lifecycle_entry() -> None:
    assert all(
        "Process acquired bodies" not in action.label
        for action in operator.build_operator_menu()
    )


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


def test_console_creates_fixture_pinned_to_active_plan(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "fixture-a")
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    _console(tmp_path).create_fixture()

    assert calls == [
        [
            "fixture",
            "create",
            "--fixture",
            "fixture-a",
            "--plan-id",
            "plan-a",
            "--artifacts",
            str(tmp_path),
        ]
    ]


def test_console_fill_confirms_only_retention_and_shows_exact_evidence(
    tmp_path, monkeypatch, capsys
) -> None:
    calls = []
    answers = iter(("2048", "yes"))
    monkeypatch.setattr(operator, "_configured_response_byte_limit", lambda: 4096)
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: next(answers))
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)
    console = _console(tmp_path)
    monkeypatch.setattr(console, "choose_fixture", lambda: "fixture-a")
    monkeypatch.setattr(console, "choose_run", lambda: "run-a")
    monkeypatch.setattr(console, "choose_run_target", lambda _run_id: "target-a")
    monkeypatch.setattr(
        console, "choose_attempt", lambda _run_id, _target_id: "attempt-a"
    )

    console.fill_fixture()

    assert calls == [
        [
            "fixture",
            "fill",
            "--fixture",
            "fixture-a",
            "--run-id",
            "run-a",
            "--target-id",
            "target-a",
            "--attempt-id",
            "attempt-a",
            "--max-response-bytes",
            "2048",
            "--artifacts",
            str(tmp_path),
        ]
    ]
    output = capsys.readouterr().out
    assert "fixture=fixture-a" in output
    assert "plan=plan-a" in output
    assert "run=run-a" in output
    assert "target=target-a" in output
    assert "attempt=attempt-a" in output
    assert "2048" in output


def test_console_run_discovery_filters_active_plan_and_paginates(
    tmp_path, monkeypatch
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    for run_id, plan_id in (("run-a", "plan-a"), ("run-b", "plan-b")):
        paths.run_dir(run_id).mkdir(parents=True)
        paths.run_manifest_path(run_id).write_text(
            json.dumps(
                {
                    "target_plan_id": plan_id,
                    "target_plan_digest": "a" * 64,
                    "target_schema_version": 1,
                    "target_row_count": 4,
                }
            ),
            encoding="utf-8",
        )
    console = _console(tmp_path)
    monkeypatch.setattr(operator, "discover_run_ids", lambda _paths: ("run-a", "run-b"))
    monkeypatch.setattr(operator, "resolve_acquisition_paths", lambda **_kwargs: paths)
    observed = {}

    def choose(items, *, prompt_label):
        observed["label"] = prompt_label
        observed["items"] = items
        return items[0]

    monkeypatch.setattr(operator, "prompt_paginated_choice", choose)

    assert console.choose_run() == "run-a"
    assert observed["label"] == "Acquisition run"
    assert [item.value for item in observed["items"]] == ["run-a"]
    assert "targets=4" in observed["items"][0].label


def test_console_target_discovery_is_paginated(tmp_path, monkeypatch) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    console = _console(tmp_path)
    monkeypatch.setattr(operator, "resolve_acquisition_paths", lambda **_kwargs: paths)
    monkeypatch.setattr(operator, "load_validated_work_order", lambda *_: ("part",))
    monkeypatch.setattr(
        operator,
        "iter_work_order_rows",
        lambda _parts: iter(
            (
                {"target_id": "target-a", "executable": True, "skip_reason": None},
                {
                    "target_id": "target-b",
                    "executable": False,
                    "skip_reason": "unresolved",
                },
            )
        ),
    )
    observed = {}

    def choose(items, *, prompt_label):
        observed["label"] = prompt_label
        observed["items"] = items
        return items[0]

    monkeypatch.setattr(operator, "prompt_paginated_choice", choose)

    assert console.choose_run_target("run-a") == "target-a"
    assert observed["label"] == "Recorded target"
    assert [item.value for item in observed["items"]] == ["target-a"]


def test_console_attempt_discovery_excludes_lazy_index_response_attempts(
    tmp_path, monkeypatch
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    console = _console(tmp_path)
    attempts = [
        SimpleNamespace(
            attempt_id="body-a",
            attempt_kind="document_body",
            attempt_number=1,
            outcome="acquired",
            source_body_relative_path="private/a.bin",
        ),
        SimpleNamespace(
            attempt_id="index-a",
            attempt_kind="lazy_index",
            attempt_number=2,
            outcome="acquired",
            source_body_relative_path="private/index.bin",
        ),
        SimpleNamespace(
            attempt_id="selected-body",
            attempt_kind="document_body",
            attempt_number=3,
            outcome="acquired",
            source_body_relative_path="private/selected.bin",
        ),
        SimpleNamespace(
            attempt_id="body-b",
            attempt_kind="document_body",
            attempt_number=4,
            outcome="failed",
            source_body_relative_path=None,
        ),
    ]
    monkeypatch.setattr(operator, "resolve_acquisition_paths", lambda **_kwargs: paths)
    monkeypatch.setattr(operator, "list_target_attempts", lambda *_: attempts)
    observed = {}

    def choose(items, *, prompt_label):
        observed["label"] = prompt_label
        observed["items"] = items
        return items[1]

    monkeypatch.setattr(operator, "prompt_paginated_choice", choose)

    assert console.choose_attempt("run-a", "target-a") == "body-b"
    assert observed["label"] == "Exact attempt"
    assert [item.value for item in observed["items"]] == ["body-a", "body-b"]
    assert "private" not in observed["items"][0].label


def test_console_declining_retention_does_not_mutate_fixture(
    tmp_path, monkeypatch
) -> None:
    answers = iter(("4096", "no"))
    calls = []
    monkeypatch.setattr(operator, "_configured_response_byte_limit", lambda: 4096)
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: next(answers))
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)
    console = _console(tmp_path)
    monkeypatch.setattr(console, "choose_fixture", lambda: "fixture-a")
    monkeypatch.setattr(console, "choose_run", lambda: "run-a")
    monkeypatch.setattr(console, "choose_run_target", lambda _run_id: "target-a")
    monkeypatch.setattr(
        console, "choose_attempt", lambda _run_id, _target_id: "attempt-a"
    )

    console.fill_fixture()

    assert calls == []


def test_console_review_generation_has_no_confirmation(tmp_path, monkeypatch) -> None:
    answers = iter(("capture-a", "target-a", "review-output"))
    calls = []
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: next(answers))
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)
    console = _console(tmp_path)
    monkeypatch.setattr(console, "choose_fixture", lambda: "fixture-a")

    console.generate_review()

    assert calls == [
        [
            "review",
            "generate",
            "--fixture",
            "fixture-a",
            "--capture-id",
            "capture-a",
            "--target-id",
            "target-a",
            "--output",
            "review-output",
            "--artifacts",
            str(tmp_path),
        ]
    ]


def test_console_selects_sorted_review_runs_for_compare_and_analysis(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "document_acquisition" / "review-runs"
    first = root / "run-a"
    second = root / "run-b"
    first.mkdir(parents=True)
    second.mkdir()
    (root / "diff-run").mkdir()
    console = _console(tmp_path)
    monkeypatch.setattr(operator, "analyze_review_run", lambda _directory: {})
    assert console.review_runs() == [first, second]
    calls = []
    answers = iter((first, second, first))
    monkeypatch.setattr(console, "choose_review_run", lambda: next(answers))
    selection_count = 0

    def choose_review(items, *, prompt_label):
        nonlocal selection_count
        assert prompt_label == "Select review run to analyze"
        selection_count += 1
        return items[1] if selection_count < 3 else items[0]

    monkeypatch.setattr(operator, "prompt_paginated_choice", choose_review)
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    console.compare_reviews()
    console.analyze_reviews()

    assert calls == [
        [
            "review",
            "compare",
            "--base",
            str(first),
            "--new",
            str(second),
            "--artifacts",
            str(tmp_path),
        ],
        [
            "review",
            "analyze",
            "--run",
            str(first),
            "--run",
            str(second),
            "--artifacts",
            str(tmp_path),
        ],
    ]
