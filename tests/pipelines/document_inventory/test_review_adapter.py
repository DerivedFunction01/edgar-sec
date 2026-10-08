"""Unit tests for InventoryReviewAdapter."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.pipelines.document_inventory.review_adapter import (
    InventoryReviewAdapter,
)


def test_adapter_identity() -> None:
    adapter = InventoryReviewAdapter()
    assert adapter.dataset_name == "document_inventory"


def test_adapter_list_fixtures(tmp_path: Path, monkeypatch) -> None:
    adapter = InventoryReviewAdapter()
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.review_adapter.discover_fixtures",
        lambda root: [{"fixture_id": "fix-1"}],
    )
    result = adapter.list_fixtures(tmp_path)
    assert len(result) == 1
    assert result[0]["fixture_id"] == "fix-1"


def test_adapter_create_and_fill(monkeypatch) -> None:
    import edgar_sec.pipelines.document_inventory.cli as inv_cli

    adapter = InventoryReviewAdapter()
    calls: list[str] = []
    monkeypatch.setattr(
        inv_cli,
        "cmd_fixture_create",
        lambda args: calls.append("create") or 0,
    )
    monkeypatch.setattr(
        inv_cli,
        "cmd_fixture_fill",
        lambda args: calls.append("fill") or 0,
    )

    assert adapter.create_fixture("f1", "p1") == 0
    assert adapter.fill_fixture("f1", "p1") == 0
    assert calls == ["create", "fill"]


def test_adapter_build_review_artifacts(tmp_path: Path, monkeypatch) -> None:
    adapter = InventoryReviewAdapter()
    calls: list = []
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.review_adapter.cmd_review_artifacts",
        lambda args: calls.append(args) or 0,
    )
    code = adapter.build_review_artifacts("f1", tmp_path, limit=5, workers=2)
    assert code == 0
    assert len(calls) == 1
    assert calls[0].fixture == "f1"
    assert calls[0].limit == 5
    assert calls[0].workers == 2


def test_adapter_compare_case_lifecycle(tmp_path: Path) -> None:
    adapter = InventoryReviewAdapter()

    diff_add = adapter.compare_case("c1", None, tmp_path / "c1")
    assert diff_add.status == "added"

    diff_rem = adapter.compare_case("c1", tmp_path / "c1", None)
    assert diff_rem.status == "removed"

    # Both present, unchanged
    base_case = tmp_path / "base"
    new_case = tmp_path / "new"
    base_case.mkdir()
    new_case.mkdir()

    (base_case / "entries.csv").write_text(
        "acc,seq,doc\n001,1,a.htm\n", encoding="utf-8"
    )
    (new_case / "entries.csv").write_text(
        "acc,seq,doc\n001,1,a.htm\n", encoding="utf-8"
    )
    (base_case / "observations.json").write_text(
        json.dumps({"status": "ok"}), encoding="utf-8"
    )
    (new_case / "observations.json").write_text(
        json.dumps({"status": "ok"}), encoding="utf-8"
    )

    diff_same = adapter.compare_case("c1", base_case, new_case)
    assert diff_same.status == "unchanged"

    # Changed observations
    (new_case / "observations.json").write_text(
        json.dumps({"status": "error"}), encoding="utf-8"
    )
    diff_changed = adapter.compare_case("c1", base_case, new_case)
    assert diff_changed.status == "changed"
    assert "observations.json" in diff_changed.details
