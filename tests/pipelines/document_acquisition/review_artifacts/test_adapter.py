from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.pipelines.document_acquisition.review_artifacts.adapter import (
    AcquisitionReviewAdapter,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureSummary,
)


def test_adapter_identity_and_fixture_discovery(tmp_path: Path, monkeypatch) -> None:
    adapter = AcquisitionReviewAdapter()
    assert adapter.dataset_name == "document_acquisition"
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.review_artifacts.adapter.list_fixture_summaries",
        lambda _paths: iter(
            (
                FixtureSummary(
                    "fixture-a", "plan-a", "a" * 64, 1, 2, 2, (("acquired", 2),)
                ),
            )
        ),
    )

    assert adapter.list_fixtures(tmp_path) == [
        {
            "fixture_id": "fixture-a",
            "target_plan_id": "plan-a",
            "target_plan_digest": "a" * 64,
            "target_plan_schema_version": 1,
            "capture_count": 2,
            "case_count": 2,
            "acquisition_status_counts": {"acquired": 2},
        }
    ]


def test_adapter_build_review_artifacts(tmp_path: Path, monkeypatch) -> None:
    adapter = AcquisitionReviewAdapter()
    calls = []
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.review_artifacts.adapter._get_cli_dep",
        lambda _name, fallback: lambda args: calls.append(args) or 0,
    )

    code = adapter.build_review_artifacts(
        "fixture-a",
        tmp_path / "review",
        limit=4,
        workers=1,
        accessions=("0000123456-12-000001",),
        artifacts_root=tmp_path,
        capture_id="capture-a",
        target_id="target-a",
        no_progress=True,
    )

    assert code == 0
    assert calls[0].fixture == "fixture-a"
    assert calls[0].capture_id == "capture-a"
    assert calls[0].target_id == "target-a"
    assert calls[0].accessions == ["0000123456-12-000001"]
    assert calls[0].no_progress


def test_compare_case_uses_processing_review_json(tmp_path: Path) -> None:
    adapter = AcquisitionReviewAdapter()
    base = tmp_path / "base"
    new = tmp_path / "new"
    base.mkdir()
    new.mkdir()
    base_artifact = base / "processing-review.json"
    new_artifact = new / "processing-review.json"
    base_artifact.write_text(json.dumps({"status": "available"}), encoding="utf-8")
    new_artifact.write_text(json.dumps({"status": "available"}), encoding="utf-8")

    assert adapter.compare_case("case-1", base, new).status == "unchanged"
    new_artifact.write_text(json.dumps({"status": "unsupported"}), encoding="utf-8")
    changed = adapter.compare_case("case-1", base, new)
    assert changed.status == "changed"
    assert changed.details == "processing-review.json"
    assert changed.patch
