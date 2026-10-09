from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import edgar_sec.pipelines.document_inventory.operator as operator
from edgar_sec.pipelines.document_inventory.run_state import InventoryRunStatus


def test_menu_exposes_operations() -> None:
    actions = operator.build_operator_menu()
    labels = {action.key: action.label for action in actions}
    assert "1" in labels and "query" in labels["1"].lower()
    assert "2" in labels and "project" in labels["2"].lower()
    assert "3" in labels and "status" in labels["3"].lower()
    assert "4" in labels and "run" in labels["4"].lower()
    assert "d" in labels and "distribution" in labels["d"].lower()
    assert "p" in labels and "dag" in labels["p"].lower()
    assert "f" in labels and "review" in labels["f"].lower()


def test_action_query_with_accession(monkeypatch) -> None:
    calls: list[Namespace] = []
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "0000000001-20-000001")
    monkeypatch.setattr(operator, "cmd_query", calls.append)
    operator._action_query()
    assert len(calls) == 1
    assert calls[0].accession == "0000000001-20-000001"
    assert calls[0].artifacts_root == operator._root()


def test_action_query_with_form_and_limit(monkeypatch) -> None:
    prompts = iter(["", "10-K", "12345", "", "50"])
    calls: list[Namespace] = []
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: next(prompts))
    monkeypatch.setattr(operator, "cmd_query", calls.append)
    operator._action_query()
    assert len(calls) == 1
    assert calls[0].form == "10-K"
    assert calls[0].filing_cik == "12345"
    assert calls[0].limit == 50
    assert calls[0].artifacts_root == operator._root()


def test_action_review_provides_plan_discovery_via_config(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple] = []
    import edgar_sec.infra.storage.review.operator as rev_op

    monkeypatch.setattr(operator, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        rev_op,
        "run_review_menu",
        lambda config: calls.append((config.adapter, config.artifacts_root)),
    )
    operator._action_review()
    assert len(calls) == 1
    assert calls[0][0].dataset_name == "document_inventory"
    assert Path(calls[0][1]) == tmp_path


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


def test_action_project_uses_paginated_choice(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operator,
        "discover_plans",
        lambda _root: [
            {"plan_id": "p-1", "catalog_id": "c-1", "scope": "deterministic"}
        ],
    )
    monkeypatch.setattr(operator, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        operator, "prompt_paginated_choice", lambda *args, **kwargs: args[0][0]
    )
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "main")
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)
    operator._action_project()
    assert calls == [
        [
            "project",
            "--catalog-plan",
            "p-1",
            "--branch",
            "main",
            "--artifacts",
            str(tmp_path),
        ]
    ]


def test_interactive_run_requires_default_no_consent(
    monkeypatch, tmp_path: Path
) -> None:
    status = InventoryRunStatus(
        run_id="run-1",
        state="projected",
        valid=True,
        error=None,
        catalog_plan_id="plan-1",
        base_snapshot_id=None,
        work_order_rows=4,
        expected_chunks=2,
        committed_chunks=0,
        outstanding_chunks=2,
        pending_accessions=4,
        invalid_chunks=0,
        retryable_failures=0,
        refused_outcomes=0,
        locked=False,
        lock_metadata=None,
        published_snapshot_id=None,
    )
    calls = []
    monkeypatch.setattr(operator, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(operator, "discover_run_statuses", lambda _root: (status,))
    monkeypatch.setattr(
        operator, "prompt_paginated_choice", lambda items, **_kwargs: items[0]
    )
    prompts = []
    monkeypatch.setattr(
        operator,
        "prompt_text",
        lambda label, default="": prompts.append((label, default)) or default,
    )
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    operator._action_run()

    assert calls == []
    assert prompts == [("Start network execution? (yes/no)", "no")]


def test_interactive_run_dispatches_after_consent(monkeypatch, tmp_path: Path) -> None:
    status = InventoryRunStatus(
        run_id="run-2",
        state="projected",
        valid=True,
        error=None,
        catalog_plan_id="plan-2",
        base_snapshot_id=None,
        work_order_rows=2,
        expected_chunks=1,
        committed_chunks=0,
        outstanding_chunks=1,
        pending_accessions=2,
        invalid_chunks=0,
        retryable_failures=0,
        refused_outcomes=0,
        locked=False,
        lock_metadata=None,
        published_snapshot_id=None,
    )
    calls = []
    monkeypatch.setattr(operator, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(operator, "discover_run_statuses", lambda _root: (status,))
    monkeypatch.setattr(
        operator, "prompt_paginated_choice", lambda items, **_kwargs: items[0]
    )
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "yes")
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    operator._action_run()

    assert calls == [["run", "--run-id", "run-2", "--artifacts", str(tmp_path)]]


def test_dag_publish_selects_existing_run_without_run_action(
    monkeypatch, tmp_path: Path
):
    status = InventoryRunStatus(
        run_id="run-ready",
        state="ready",
        valid=True,
        error=None,
        catalog_plan_id="plan-ready",
        base_snapshot_id="snapshot-base",
        work_order_rows=1,
        expected_chunks=1,
        committed_chunks=1,
        outstanding_chunks=0,
        pending_accessions=0,
        invalid_chunks=0,
        retryable_failures=0,
        refused_outcomes=0,
        locked=False,
        lock_metadata=None,
        published_snapshot_id=None,
    )
    calls = []
    monkeypatch.setattr(operator, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(operator, "discover_run_statuses", lambda _root: (status,))
    monkeypatch.setattr(
        operator, "prompt_paginated_choice", lambda items, **_kwargs: items[0]
    )
    monkeypatch.setattr(operator, "prompt_text", lambda *_args: "feature")
    monkeypatch.setattr(operator, "cli_main", lambda args: calls.append(args) or 0)

    operator._action_publish_existing()

    assert calls == [
        [
            "publish",
            "--run-id",
            "run-ready",
            "--branch",
            "feature",
            "--artifacts",
            str(tmp_path),
        ]
    ]
