import json

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.review.paths import PIPELINE_REVIEW_MANIFEST_FILE
from edgar_sec.pipelines.document_acquisition.review_artifacts.holdout import (
    HoldoutAnalysisError,
    analyze_holdout_labels,
    analyze_holdout_review_run,
)
from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.pipelines.document_acquisition.review_artifacts.labels import (
    build_review_label,
    write_review_label,
)


def _label(
    *,
    accession: str,
    review_sha: str,
    body_sha: str,
    outcome: str,
    predicted: str,
    annotator: str,
) -> dict[str, object]:
    identity = {
        "authority_id": "reg_s_k_item_601",
        "code": "3.1",
    }
    record: dict[str, object] = {
        "artifact_type": "document_acquisition.exhibit_label",
        "artifact_version": 1,
        "label_scope": "planned_exhibit_identity",
        "fixture_id": "fixture-" + accession[-6:],
        "capture_id": "capture-" + accession[-6:],
        "target_id": "target-" + accession[-6:],
        "accession": accession,
        "issuer_cik": accession[:10],
        "accession_year_code": accession[11:13],
        "form": "10-K",
        "target_type": "EX-3.1",
        "selected_sha256": body_sha,
        "processing_review_sha256": review_sha,
        "assessment_fingerprint": "e" * 64,
        "predicted_outcome": predicted,
        "expected_identity": identity,
        "versions": {
            "evaluator_version": "v1",
            "taxonomy_version": "v1",
            "profile_id": "reg_s_k_item_601",
            "profile_version": "v1",
            "pack_id": "ex3_1",
            "pack_version": "v1",
        },
        "outcome": outcome,
        "observed_kind": "exhibit" if outcome == "positive" else "primary_report",
        "observed_identity": identity if outcome == "positive" else None,
        "annotator_id": annotator,
        "annotation_kind": "independent",
        "annotated_at_utc": "2026-10-13T20:00:00Z",
        "evidence_ref": "normalized-text:chars-0-43",
        "rationale": "reviewed",
        "supersedes_label_sha256": [],
    }
    record["artifact_sha256"] = canonical_hash(record)
    return record


def _consensus_case(
    accession: str,
    *,
    outcome: str,
    predicted: str,
    sequence: int,
    body_sequence: int | None = None,
) -> tuple[dict[str, object], ...]:
    return tuple(
        _label(
            accession=accession,
            review_sha=chr(97 + sequence) * 64,
            body_sha=chr(100 + (sequence if body_sequence is None else body_sequence))
            * 64,
            outcome=outcome,
            predicted=predicted,
            annotator=annotator,
        )
        for annotator in ("reviewer-a", "reviewer-b")
    )


def test_holdout_report_is_issuer_and_time_disjoint_with_form_family_counts():
    labels = (
        *_consensus_case(
            "0000000001-22-000001",
            outcome="positive",
            predicted="positive",
            sequence=0,
        ),
        *_consensus_case(
            "0000000002-24-000001",
            outcome="negative",
            predicted="positive",
            sequence=1,
        ),
        *_consensus_case(
            "0000000003-25-000001",
            outcome="positive",
            predicted="ambiguous",
            sequence=2,
        ),
    )
    spec = {
        "schema_version": 1,
        "protocol_id": "holdout-v1",
        "accession_century": 2000,
        "training_end_year": 2022,
        "holdout_start_year": 2023,
        "holdout_end_year": 2025,
        "holdout_ciks": ["0000000002", "0000000003"],
    }

    report = analyze_holdout_labels(labels, spec)

    assert report["labeled_training_cases"] == 1
    assert report["labeled_holdout_cases"] == 2
    assert report["holdout_issuers_observed"] == 2
    assert report["near_duplicate_review"] == "not_performed"
    metrics = report["family_form_metrics"][0]
    assert (metrics["form"], metrics["family"]) == ("10-K", "EX-3.1")
    assert metrics["false_positives"] == 1
    assert metrics["false_negatives"] == 1
    assert metrics["prediction_abstentions"] == 1


def test_holdout_partition_rejects_duplicate_bodies_and_time_overlap():
    labels = _consensus_case(
        "0000000002-24-000001",
        outcome="negative",
        predicted="positive",
        sequence=1,
    ) + _consensus_case(
        "0000000003-24-000001",
        outcome="positive",
        predicted="positive",
        sequence=2,
        body_sequence=1,
    )
    spec = {
        "schema_version": 1,
        "protocol_id": "holdout-v1",
        "accession_century": 2000,
        "training_end_year": 2022,
        "holdout_start_year": 2023,
        "holdout_end_year": 2025,
        "holdout_ciks": ["0000000002", "0000000003"],
    }

    with pytest.raises(HoldoutAnalysisError, match="duplicate selected bodies"):
        analyze_holdout_labels(labels, spec)

    spec["training_end_year"] = 2024
    with pytest.raises(HoldoutAnalysisError, match="specification"):
        analyze_holdout_labels(labels, spec)


def _write_review_case(
    root, records, *, sequence, accession, selected_sha, disposition
):
    fixture_id = f"fixture-{sequence}"
    capture_id = f"capture-{sequence}"
    target_id = f"target-{sequence}"
    plan_digest = "a" * 64
    artifact = {
        "artifact_type": "document_acquisition.processing_review",
        "artifact_version": 2,
        "fixture": {
            "fixture_id": fixture_id,
            "capture_id": capture_id,
            "target_id": target_id,
            "capture_run_id": "source-run",
            "target_plan_id": "plan-a",
            "target_plan_digest": plan_digest,
            "target_plan_schema_version": 1,
            "selected_sha256": selected_sha,
        },
        "run_id": "source-run",
        "target_id": target_id,
        "accession": accession,
        "form": "10-K",
        "target_role": "exhibit",
        "target_type": "EX-3.1",
        "processing": {
            "operations": [{"operation_id": "raw", "status": "available"}],
            "exhibit_assessment": {
                "expected_role": "exhibit",
                "expected_type": "EX-3.1",
                "expected_identity": {
                    "authority_id": "reg_s_k_item_601",
                    "code": "3.1",
                },
                "disposition": disposition,
                "evaluator_version": "v1",
                "taxonomy_version": "v1",
                "profile_id": "reg_s_k_item_601",
                "profile_version": "v1",
                "pack_id": "ex3_1",
                "pack_version": "v1",
            },
            "exhibit_assessment_fingerprint": "c" * 64,
        },
    }
    artifact["artifact_sha256"] = canonical_hash(artifact)
    case_root = root / "cases" / f"case-{sequence}"
    case_root.mkdir(parents=True)
    artifact_path = case_root / "processing-review.json"
    artifact_path.write_text(canonical_json(artifact), encoding="utf-8")
    records.append(
        {
            "review_id": root.name,
            "fixture_id": fixture_id,
            "capture_id": capture_id,
            "target_id": target_id,
            "accession": accession,
            "run_id": "source-run",
            "target_plan_id": "plan-a",
            "target_plan_digest": plan_digest,
            "target_plan_schema_version": 1,
            "status": "complete",
            "outputs": {
                "processing-review.json": {
                    "path": f"cases/case-{sequence}/processing-review.json",
                    "sha256": file_sha256(artifact_path),
                }
            },
        }
    )
    outcome = "positive" if disposition == "consistent" else "negative"
    observed_kind = "exhibit" if outcome == "positive" else "primary_report"
    observed_identity = (
        ExhibitIdentity("reg_s_k_item_601", "3.1") if outcome == "positive" else None
    )
    for annotator in ("reviewer-a", "reviewer-b"):
        label = build_review_label(
            artifact,
            outcome=outcome,
            observed_kind=observed_kind,
            observed_identity=observed_identity,
            annotator_id=annotator,
            annotated_at_utc="2026-10-13T20:00:00Z",
            evidence_ref="normalized-text:chars-0-43",
        )
        write_review_label(root, artifact, label)


def test_holdout_review_run_validates_artifacts_labels_and_output(tmp_path):
    root = tmp_path / "review-holdout"
    root.mkdir()
    records = []
    _write_review_case(
        root,
        records,
        sequence=1,
        accession="0000000001-22-000001",
        selected_sha="d" * 64,
        disposition="consistent",
    )
    _write_review_case(
        root,
        records,
        sequence=2,
        accession="0000000002-24-000001",
        selected_sha="e" * 64,
        disposition="consistent",
    )
    (root / PIPELINE_REVIEW_MANIFEST_FILE).write_text(
        "".join(canonical_json(record) + "\n" for record in records),
        encoding="utf-8",
    )
    spec = {
        "schema_version": 1,
        "protocol_id": "holdout-run-v1",
        "accession_century": 2000,
        "training_end_year": 2022,
        "holdout_start_year": 2023,
        "holdout_end_year": 2025,
        "holdout_ciks": ["0000000002"],
    }
    output = tmp_path / "holdout.json"

    report = analyze_holdout_review_run(root, spec, output=output)

    assert report["labeled_training_cases"] == 1
    assert report["labeled_holdout_cases"] == 1
    assert json.loads(output.read_text("utf-8")) == report
