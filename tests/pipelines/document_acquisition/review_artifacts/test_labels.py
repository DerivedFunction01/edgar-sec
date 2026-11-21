import json

import pytest

from edgar_sec.domain.forms.common.exhibits import ExhibitIdentity
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.review_artifacts.labels import (
    ReviewLabelError,
    build_review_label,
    load_case_review_labels,
    validate_review_label,
    write_review_label,
)


def _review_artifact() -> dict[str, object]:
    artifact: dict[str, object] = {
        "artifact_type": "document_acquisition.processing_review",
        "artifact_version": 4,
        "fixture": {
            "fixture_id": "fixture_exhibit",
            "capture_id": "capture_exhibit",
            "target_id": "target_exhibit",
            "body_sha256": "a" * 64,
        },
        "capture_id": "capture_exhibit",
        "target_id": "target_exhibit",
        "accession": "0000320193-25-000001",
        "form": "10-K",
        "target_role": "exhibit",
        "target_type": "EX-3.1",
        "processing": {
            "outputs": {},
            "exhibit_assessment": {
                "expected_role": "exhibit",
                "expected_type": "EX-3.1",
                "expected_identity": {
                    "authority_id": "reg_s_k_item_601",
                    "code": "3.1",
                },
                "disposition": "consistent",
                "evaluator_version": "v1",
                "taxonomy_version": "v1",
                "profile_id": "reg_s_k_item_601",
                "profile_version": "v1",
                "pack_id": "ex3_1",
                "pack_version": "v1",
            },
            "exhibit_assessment_fingerprint": "b" * 64,
        },
    }
    artifact["artifact_sha256"] = canonical_hash(artifact)
    return artifact


def test_label_pins_body_review_and_versioned_assessment(tmp_path):
    review = _review_artifact()
    label = build_review_label(
        review,
        outcome="positive",
        observed_kind="exhibit",
        observed_identity=ExhibitIdentity("reg_s_k_item_601", "3.1"),
        annotator_id="reviewer-a",
        annotated_at_utc="2026-10-13T20:00:00Z",
        evidence_ref="normalized-text:chars-0-43",
        rationale="The selected body matches the planned exhibit.",
    )

    validate_review_label(label, review)
    path = write_review_label(tmp_path, review, label)
    repeated = write_review_label(tmp_path, review, label)

    assert repeated == path
    assert path.parent.name == "target_exhibit"
    assert json.loads(path.read_text("utf-8")) == label
    assert load_case_review_labels(tmp_path, review) == (label,)
    assert label["issuer_cik"] == "0000320193"
    assert label["accession_year_code"] == "25"
    assert label["assessment_fingerprint"] == "b" * 64


def test_negative_label_requires_a_conflicting_observed_identity():
    review = _review_artifact()
    label = build_review_label(
        review,
        outcome="negative",
        observed_kind="primary_report",
        annotator_id="reviewer-b",
        annotated_at_utc="2026-10-13T20:00:00+00:00",
        evidence_ref="normalized-text:chars-0-100",
    )

    validate_review_label(label, review)
    altered = {**label, "selected_sha256": "c" * 64}
    with pytest.raises(ReviewLabelError, match="digest"):
        validate_review_label(altered, review)


def test_label_rejects_unpinned_or_invalid_annotations():
    review = _review_artifact()
    with pytest.raises(ReviewLabelError, match="UTC"):
        build_review_label(
            review,
            outcome="ambiguous",
            observed_kind="unknown",
            annotator_id="reviewer-a",
            annotated_at_utc="2026-10-13T20:00:00",
            evidence_ref="normalized-text:chars-0-100",
        )


def test_disagreement_is_preserved_and_adjudicated_with_a_new_sidecar(tmp_path):
    review = _review_artifact()
    positive = build_review_label(
        review,
        outcome="positive",
        observed_kind="exhibit",
        observed_identity=ExhibitIdentity("reg_s_k_item_601", "3.1"),
        annotator_id="reviewer-a",
        annotated_at_utc="2026-10-13T20:00:00Z",
        evidence_ref="normalized-text:chars-0-43",
    )
    negative = build_review_label(
        review,
        outcome="negative",
        observed_kind="primary_report",
        annotator_id="reviewer-b",
        annotated_at_utc="2026-10-13T20:01:00Z",
        evidence_ref="normalized-text:chars-0-43",
    )
    write_review_label(tmp_path, review, positive)
    write_review_label(tmp_path, review, negative)
    adjudication = build_review_label(
        review,
        outcome="positive",
        observed_kind="exhibit",
        observed_identity=ExhibitIdentity("reg_s_k_item_601", "3.1"),
        annotator_id="adjudicator-c",
        annotated_at_utc="2026-10-13T20:02:00Z",
        evidence_ref="normalized-text:chars-0-43",
        annotation_kind="adjudication",
        supersedes_label_sha256=(
            positive["artifact_sha256"],
            negative["artifact_sha256"],
        ),
    )

    write_review_label(tmp_path, review, adjudication)
    labels = load_case_review_labels(tmp_path, review)

    assert len(labels) == 3
    assert sum(label["annotation_kind"] == "adjudication" for label in labels) == 1
    with pytest.raises(ReviewLabelError, match="conflicts"):
        build_review_label(
            review,
            outcome="positive",
            observed_kind="primary_report",
            annotator_id="reviewer-a",
            annotated_at_utc="2026-10-13T20:00:00Z",
            evidence_ref="normalized-text:chars-0-100",
        )
