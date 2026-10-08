"""Unit tests for the interactive review operator console."""

from pathlib import Path

from edgar_sec.infra.storage.review.models import CaseDiff
from edgar_sec.infra.storage.review.operator import (
    ReviewMenuConfig,
    run_review_menu,
)


class RecordingAdapter:
    dataset_name = "test_inventory"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_fixtures(self, _root):
        self.calls.append("list")
        return [
            {
                "fixture_id": "fix-aaa",
                "page_count": 1,
                "accession_count": 10,
                "capture_state": "complete",
            },
            {
                "fixture_id": "fix-bbb",
                "page_count": 2,
                "accession_count": 20,
                "capture_state": "partial",
            },
        ]

    def create_fixture(self, *_a, **_k):
        self.calls.append("create")
        return 0

    def fill_fixture(self, *_a, **_k):
        self.calls.append("fill")
        return 0

    def build_review_artifacts(self, *_a, **_k):
        self.calls.append("generate")
        return 0

    def compare_case(self, case_id: str, _b, _n) -> CaseDiff:
        return CaseDiff(case_id, "unchanged")


def test_list_fixtures_runs_and_exits(tmp_path: Path, monkeypatch) -> None:
    adapter = RecordingAdapter()
    answers = iter(["3", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))

    config = ReviewMenuConfig(adapter=adapter, artifacts_root=tmp_path)
    exit_code = run_review_menu(config)
    assert exit_code == 0
    assert adapter.calls == ["list"]


def test_create_fixture_uses_the_provided_plan_and_proposes_fx_default(
    tmp_path: Path, monkeypatch
) -> None:
    import json

    adapter = RecordingAdapter()
    plans_dir = tmp_path / "plans"
    plan_subdir = plans_dir / "94ea5ab57122d607532cbc93"
    plan_subdir.mkdir(parents=True)
    (plan_subdir / "plan.json").write_text(
        json.dumps(
            {
                "plan_id": "94ea5ab57122d607532cbc93",
                "catalog_id": "f259fde5",
                "scope": "policy",
                "selected_rows": 506,
            }
        ),
        encoding="utf-8",
    )

    answers = iter(["1", "", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))

    config = ReviewMenuConfig(
        adapter=adapter,
        plans_root=plans_dir,
        artifacts_root=tmp_path,
    )
    assert run_review_menu(config) == 0
    assert adapter.calls == ["create"]


def test_create_exits_cleanly_when_no_plans_are_available(
    tmp_path: Path, monkeypatch
) -> None:
    adapter = RecordingAdapter()
    answers = iter(["1", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))

    config = ReviewMenuConfig(adapter=adapter, artifacts_root=tmp_path)
    assert run_review_menu(config) == 0
    assert adapter.calls == []


def test_fill_selects_a_fixture_via_paginated_choice_and_applies_the_plan(
    tmp_path: Path, monkeypatch
) -> None:
    adapter = RecordingAdapter()

    answers = iter(["2", "1", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))

    config = ReviewMenuConfig(
        adapter=adapter,
        plan_id="94ea5ab57122d607532cbc93",
        artifacts_root=tmp_path,
    )
    assert run_review_menu(config) == 0
    assert adapter.calls == ["list", "fill"]


def test_generate_builds_artifacts_to_an_auto_derived_run_dir(
    tmp_path: Path, monkeypatch
) -> None:
    adapter = RecordingAdapter()
    answers = iter(["4", "1", "", "", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))

    config = ReviewMenuConfig(adapter=adapter, artifacts_root=tmp_path)
    assert run_review_menu(config) == 0
    assert adapter.calls == ["list", "generate"]


def test_compare_blocks_when_no_review_runs_exist(tmp_path: Path, monkeypatch) -> None:
    adapter = RecordingAdapter()
    answers = iter(["5", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))

    config = ReviewMenuConfig(adapter=adapter, artifacts_root=tmp_path)
    assert run_review_menu(config) == 0
    assert adapter.calls == []


def test_compare_blocks_with_a_single_review_run(tmp_path: Path, monkeypatch) -> None:
    adapter = RecordingAdapter()
    (tmp_path / "run-20260101_000000").mkdir()
    answers = iter(["5", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))

    config = ReviewMenuConfig(adapter=adapter, artifacts_root=tmp_path)
    assert run_review_menu(config) == 0
    assert adapter.calls == []


def test_compare_selects_runs_with_smart_defaults_and_renders_summary(
    tmp_path: Path, monkeypatch
) -> None:
    adapter = RecordingAdapter()
    (tmp_path / "run-20260101_000000").mkdir()
    (tmp_path / "run-20260102_000000").mkdir()
    answers = iter(["5", "", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))

    config = ReviewMenuConfig(adapter=adapter, artifacts_root=tmp_path)
    assert run_review_menu(config) == 0
    assert adapter.calls == []
