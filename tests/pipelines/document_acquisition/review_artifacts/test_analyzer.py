from __future__ import annotations

import json

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.review.paths import PIPELINE_REVIEW_MANIFEST_FILE
from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.pipelines.document_acquisition.review_artifacts.analyzer import (
    ReviewAnalysisError,
    analyze_review_runs,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.labels import (
    build_review_label,
    write_review_label,
)


def _write_review_run(root):
    root.mkdir()
    case_root = root / "cases" / "case-a"
    case_root.mkdir(parents=True)
    artifact = {
        "artifact_type": "document_acquisition.processing_review",
        "artifact_version": 4,
        "fixture": {
            "fixture_id": "fixture-a",
            "capture_id": "capture-a",
            "target_id": "target-a",
            "target_plan_id": "plan-a",
            "target_plan_digest": "a" * 64,
            "target_plan_schema_version": 1,
            "body_sha256": "b" * 64,
        },
        "capture_id": "capture-a",
        "target_id": "target-a",
        "accession": "0000000001-24-000001",
        "processing": {
            "outputs": {},
            "operations": [
                {"operation_id": "raw", "status": "available"},
                {"operation_id": "xml", "status": "unsupported"},
            ],
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
                "label_annotation_counts": {
                    "positive": 0,
                    "negative": 0,
                    "ambiguous": 0,
                },
                "unresolved_label_cases": 0,
                "family_form_metrics": [],
                "family_reports": [],
            }
        ],
    }
    assert analyze_review_runs((run,)) == report
    assert (artifact_path.read_bytes(), manifest_path.read_bytes()) == originals


def test_review_analysis_reports_consensus_labels_by_form_and_family(tmp_path) -> None:
    run = tmp_path / "run-labeled"
    artifact_path, manifest_path = _write_review_run(run)
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["artifact_version"] = 4
    artifact["form"] = "10-K"
    artifact["target_role"] = "exhibit"
    artifact["target_type"] = "EX-3.1"
    artifact["fixture"]["body_sha256"] = "b" * 64
    artifact["processing"]["exhibit_assessment"] = {
        "expected_role": "exhibit",
        "expected_type": "EX-3.1",
        "expected_identity": {
            "authority_id": "reg_s_k_item_601",
            "code": "3.1",
        },
        "evaluator_version": "v1",
        "taxonomy_version": "v1",
        "profile_id": "reg_s_k_item_601",
        "profile_version": "v1",
        "pack_id": "ex3_1",
        "pack_version": "v1",
        "disposition": "consistent",
    }
    artifact["processing"]["exhibit_assessment_fingerprint"] = "c" * 64
    artifact["artifact_sha256"] = canonical_hash(
        {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    )
    artifact_path.write_text(canonical_json(artifact), encoding="utf-8")
    records = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    records[0]["outputs"]["processing-review.json"]["sha256"] = file_sha256(
        artifact_path
    )
    manifest_path.write_text(
        "".join(canonical_json(record) + "\n" for record in records),
        encoding="utf-8",
    )
    for annotator in ("reviewer-a", "reviewer-b"):
        label = build_review_label(
            artifact,
            outcome="positive",
            observed_kind="exhibit",
            observed_identity=ExhibitIdentity("reg_s_k_item_601", "3.1"),
            annotator_id=annotator,
            annotated_at_utc="2026-10-13T20:00:00Z",
            evidence_ref="normalized-text:chars-0-43",
        )
        write_review_label(run, artifact, label)

    report = analyze_review_runs((run,))
    result = report["runs"][0]

    assert result["label_annotation_counts"] == {
        "positive": 2,
        "negative": 0,
        "ambiguous": 0,
    }
    assert result["family_form_metrics"][0]["form"] == "10-K"
    assert result["family_form_metrics"][0]["family"] == "EX-3.1"
    assert result["family_form_metrics"][0]["true_positives"] == 1


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
