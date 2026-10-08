"""Unit tests for the interactive review operator console."""

from pathlib import Path

from edgar_sec.infra.storage.review.models import CaseDiff
from edgar_sec.infra.storage.review.operator import run_review_menu


class RecordingAdapter:
    dataset_name = "test_inventory"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_fixtures(self, _root):
        self.calls.append("list")
        return [{"fixture_id": "fix-1"}]

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


def test_operator_runs_actions_and_exits(tmp_path: Path, monkeypatch) -> None:
    adapter = RecordingAdapter()
    answers = iter(["3", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))

    exit_code = run_review_menu(adapter, artifacts_root=tmp_path)
    assert exit_code == 0
    assert "list" in adapter.calls
