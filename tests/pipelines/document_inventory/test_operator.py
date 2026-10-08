from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import edgar_sec.pipelines.document_inventory.operator as operator


def test_menu_exposes_operations() -> None:
    actions = operator.build_operator_menu()
    labels = {action.key: action.label for action in actions}
    assert "1" in labels and "query" in labels["1"].lower()
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


def test_action_review_delegates_to_review_menu(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple] = []
    import edgar_sec.infra.storage.review.operator as rev_op

    monkeypatch.setattr(operator, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        rev_op,
        "run_review_menu",
        lambda adapter, artifacts_root: calls.append((adapter, artifacts_root)),
    )
    operator._action_review()
    assert len(calls) == 1
    assert calls[0][0].dataset_name == "document_inventory"
    assert calls[0][1] == tmp_path


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
