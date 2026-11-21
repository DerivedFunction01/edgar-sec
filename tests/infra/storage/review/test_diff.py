"""Unit tests for multi-format diff comparators and run comparison."""

import json
from pathlib import Path

from edgar_sec.infra.storage.review.diff import (
    compare_review_runs,
    diff_dataset,
    diff_json,
    diff_text,
    flatten_json,
)
from edgar_sec.infra.storage.review.models import CaseDiff


class StubReviewAdapter:
    dataset_name = "test_dataset"

    def list_fixtures(self, _root):
        return []

    def create_fixture(self, *_a, **_k):
        return 0

    def fill_fixture(self, *_a, **_k):
        return 0

    def build_review_artifacts(self, *_a, **_k):
        return 0

    def compare_case(
        self, case_id: str, base_dir: Path | None, new_dir: Path | None
    ) -> CaseDiff:
        if case_id == "case-changed":
            return CaseDiff(
                case_id,
                "changed",
                added_count=1,
                removed_count=0,
                details="entries.csv (+1/-0)",
                patch="+ row",
            )
        return CaseDiff(case_id, "unchanged")


def test_diff_text_computes_unified_diff_and_counts() -> None:
    added, removed, patch = diff_text(
        "line 1\nline 2\n", "line 1\nline 2 mod\nline 3\n"
    )
    assert added == 2
    assert removed == 1
    assert "--- base" in patch
    assert "+++ new" in patch


def test_flatten_json_flattens_nested_structures() -> None:
    data = {"a": {"b": 1}, "c": [{"d": 2}, {"d": 3}]}
    flat = flatten_json(data)
    assert flat["a.b"] == 1
    assert flat["c[0].d"] == 2
    assert flat["c[1].d"] == 3


def test_diff_json_detects_additions_removals_and_modifications() -> None:
    base = {"a": 1, "b": {"c": 2}}
    new = {"a": 10, "b": {"c": 2}, "d": 4}
    added, removed, patch = diff_json(base, new, label="test.json")
    assert added == 2
    assert removed == 1
    assert "+ a: 10" in patch
    assert "- a: 1" in patch
    assert "+ d: 4" in patch


def test_diff_dataset_detects_csv_row_differences_via_duckdb(tmp_path: Path) -> None:
    base_csv = tmp_path / "base.csv"
    new_csv = tmp_path / "new.csv"
    base_csv.write_text("id,val\n1,a\n2,b\n", encoding="utf-8")
    new_csv.write_text("id,val\n1,a\n2,b_mod\n3,c\n", encoding="utf-8")
    added, removed, patch = diff_dataset(base_csv, new_csv)
    assert added == 2
    assert removed == 1
    assert "+2 / -1" in patch


def test_compare_review_runs_generates_summary_and_patches(tmp_path: Path) -> None:
    base_run = tmp_path / "base"
    new_run = tmp_path / "new"
    output_dir = tmp_path / "diff"
    (base_run / "cases" / "case-changed").mkdir(parents=True)
    (base_run / "cases" / "case-same").mkdir(parents=True)
    (new_run / "cases" / "case-changed").mkdir(parents=True)
    (new_run / "cases" / "case-same").mkdir(parents=True)

    summary = compare_review_runs(base_run, new_run, output_dir, StubReviewAdapter())
    assert summary.total_cases == 2
    assert summary.unchanged_count == 1
    assert summary.changed_count == 1
    assert (output_dir / "summary.txt").is_file()
    assert (output_dir / "diff_manifest.json").is_file()
    assert (output_dir / "patches" / "case-changed.patch").is_file()
