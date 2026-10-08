"""Unit tests for review and fixture CLI subparser bindings."""

import argparse
from pathlib import Path

from edgar_sec.infra.storage.review.cli import attach_review_subparsers
from edgar_sec.infra.storage.review.models import CaseDiff


class RecordingAdapter:
    dataset_name = "test_inventory"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def list_fixtures(self, artifacts_root: Path | str):
        self.calls.append(("list_fixtures", {"root": artifacts_root}))
        return [{"fixture_id": "fix-1", "case_count": 10}]

    def create_fixture(
        self,
        fixture_id: str,
        catalog_plan: str,
        limit=None,
        artifacts_root="",
        json=False,
    ):
        self.calls.append(
            ("create", {"id": fixture_id, "plan": catalog_plan, "limit": limit})
        )
        return 0

    def fill_fixture(
        self,
        fixture_id: str,
        catalog_plan: str,
        limit=None,
        artifacts_root="",
        json=False,
    ):
        self.calls.append(
            ("fill", {"id": fixture_id, "plan": catalog_plan, "limit": limit})
        )
        return 0

    def build_review_artifacts(
        self,
        fixture_id: str,
        output_dir: Path,
        limit=None,
        workers=None,
        accessions=None,
        artifacts_root="",
    ):
        self.calls.append(("generate", {"id": fixture_id, "out": output_dir}))
        return 0

    def compare_case(
        self, case_id: str, base_dir: Path | None, new_dir: Path | None
    ) -> CaseDiff:
        return CaseDiff(case_id, "unchanged")


def test_cli_dispatches_generate_and_fixture_commands(tmp_path: Path) -> None:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    adapter = RecordingAdapter()
    attach_review_subparsers(subs, adapter)

    args = parser.parse_args(
        ["review", "generate", "--fixture", "f1", "--output", str(tmp_path / "out")]
    )
    args.func(args)
    assert adapter.calls[-1][0] == "generate"
    assert adapter.calls[-1][1]["id"] == "f1"

    args = parser.parse_args(
        ["fixture", "create", "--fixture", "f2", "--catalog-plan", "p1"]
    )
    args.func(args)
    assert adapter.calls[-1][0] == "create"
    assert adapter.calls[-1][1]["id"] == "f2"

    args = parser.parse_args(["fixture", "list"])
    args.func(args)
    assert adapter.calls[-1][0] == "list_fixtures"
