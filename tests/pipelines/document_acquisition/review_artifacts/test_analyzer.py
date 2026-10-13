from __future__ import annotations

import json

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.review.paths import PIPELINE_REVIEW_MANIFEST_FILE
from edgar_sec.pipelines.document_acquisition.review_artifacts.analyzer import (
    ReviewAnalysisError,
    analyze_review_runs,
)


def _write_review_run(root):
    root.mkdir()
    case_root = root / "cases" / "case-a"
    case_root.mkdir(parents=True)
    artifact = {
        "artifact_type": "document_acquisition.processing_review",
        "artifact_version": 1,
        "fixture": {
            "fixture_id": "fixture-a",
            "capture_id": "capture-a",
            "target_id": "target-a",
            "capture_run_id": "source-run",
            "target_plan_id": "plan-a",
            "target_plan_digest": "a" * 64,
            "target_plan_schema_version": 1,
        },
        "run_id": "source-run",
        "target_id": "target-a",
        "accession": "0000000001-24-000001",
        "processing": {
            "operations": [
                {"operation_id": "raw", "status": "available"},
                {"operation_id": "xml", "status": "unsupported"},
            ]
        },
    }
    artifact["artifact_sha256"] = canonical_hash(artifact)
    artifact_path = case_root / "processing-review.json"
    artifact_path.write_text(canonical_json(artifact), encoding="utf-8")
    records = [
        {
            "review_id": root.name,
            "fixture_id": "fixture-a",
            "capture_id": "capture-a",
            "target_id": "target-a",
            "accession": "0000000001-24-000001",
            "run_id": "source-run",
            "target_plan_id": "plan-a",
            "target_plan_digest": "a" * 64,
            "target_plan_schema_version": 1,
            "status": "complete",
            "outputs": {
                "processing-review.json": {
                    "path": "cases/case-a/processing-review.json",
                    "sha256": file_sha256(artifact_path),
                }
            },
        },
        {
            "review_id": root.name,
            "fixture_id": "fixture-a",
            "capture_id": "capture-a",
            "target_id": "target-b",
            "accession": "0000000001-24-000001",
            "run_id": "source-run",
            "target_plan_id": "plan-a",
            "target_plan_digest": "a" * 64,
            "target_plan_schema_version": 1,
            "status": "fixture_verification_failure",
            "outputs": {},
        },
    ]
    (root / PIPELINE_REVIEW_MANIFEST_FILE).write_text(
        "".join(canonical_json(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return artifact_path, root / PIPELINE_REVIEW_MANIFEST_FILE


def test_review_analysis_validates_artifacts_and_aggregates_deterministically(
    tmp_path,
) -> None:
    run = tmp_path / "run-a"
    artifact_path, manifest_path = _write_review_run(run)
    originals = (artifact_path.read_bytes(), manifest_path.read_bytes())

    report = analyze_review_runs((run,))

    assert report == {
        "schema_version": 1,
        "runs": [
            {
                "review_id": "run-a",
                "total_cases": 2,
                "case_status_counts": {
                    "complete": 1,
                    "fixture_verification_failure": 1,
                },
                "operation_status_counts": {"available": 1, "unsupported": 1},
            }
        ],
    }
    assert analyze_review_runs((run,)) == report
    assert (artifact_path.read_bytes(), manifest_path.read_bytes()) == originals


def test_review_analysis_refuses_a_tampered_case_output(tmp_path) -> None:
    run = tmp_path / "run-a"
    artifact_path, _ = _write_review_run(run)
    artifact_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ReviewAnalysisError, match="artifact digest differs"):
        analyze_review_runs((run,))


def test_review_analysis_writes_a_separate_explicit_report(tmp_path) -> None:
    run = tmp_path / "run-a"
    _write_review_run(run)
    output = tmp_path / "analysis.json"

    analyze_review_runs((run,), output=output)

    assert (
        json.loads(output.read_text(encoding="utf-8"))["runs"][0]["review_id"]
        == "run-a"
    )
