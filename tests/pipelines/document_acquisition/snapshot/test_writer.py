from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.dag.publication import StaleParentError
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    project_acquisition_run,
)
from edgar_sec.pipelines.document_acquisition.run_state.operations import (
    operation_attempt_id,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    MATCHER_VERSION,
    OPERATION_INPUT_SCHEMA_VERSION,
    PLAN_BUNDLE_SCHEMA_VERSION,
    RESOLVED_OPERATION_SCHEMA_VERSION,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
    TARGET_SCHEMA_VERSION,
)
from edgar_sec.pipelines.document_acquisition.snapshot.errors import (
    ReferentialIntegrityError,
    RunNotPublishableError,
)
from edgar_sec.pipelines.document_acquisition.snapshot.writer import (
    publish_acquisition_run,
    read_publication_receipt,
)
from tests.pipelines.document_acquisition.plan_projection.plan_fixture import (
    write_plan_bundle,
)


def _make_plan(artifacts_root: Path) -> Path:
    identity = {
        "bundle_schema_version": PLAN_BUNDLE_SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "target_operation_schema_version": TARGET_OPERATION_SCHEMA_VERSION,
        "source_request_schema_version": SOURCE_REQUEST_SCHEMA_VERSION,
        "operation_input_schema_version": OPERATION_INPUT_SCHEMA_VERSION,
        "matcher_version": MATCHER_VERSION,
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
        "profile_digest": "c" * 64,
        "catalog_plan_id": "catalog-fixture",
        "catalog_plan_digest": "a" * 64,
        "inventory_snapshot_id": "snapshot-fixture",
        "inventory_snapshot_digest": "b" * 64,
    }
    plan_id = f"dplan_{canonical_hash(identity)[:32]}"
    plan_root = artifacts_root / "document_planning" / "plans" / plan_id
    plan_root.mkdir(parents=True, exist_ok=True)
    accession = "0000000001-24-000001"
    target = {
        "target_id": "",
        "accession": accession,
        "form": "10-K",
        "filing_date": "2024-01-01",
        "request_id": "primary:0",
        "target_role": "primary",
        "target_type": "primary",
        "optional": False,
        "inventory_entry_id": "entry-0",
        "status": "matched",
        "status_reason": None,
        "source_origin": "inventory_index",
        "retrieval_mode": "direct_url",
        "target_url": "https://www.sec.gov/Archives/edgar/data/1/000000000124000001/report.htm",
        "sequence": None,
        "byte_size": 32,
        "availability_evidence": "index_html",
        "catalog_direct_selection": None,
    }
    target["target_id"] = canonical_hash(
        [
            plan_id,
            accession,
            target["request_id"],
            target["inventory_entry_id"],
            target["status"],
        ]
    )
    write_plan_bundle(plan_root, plan_id, identity, [target])
    return plan_root


def _setup_run(
    artifacts_root: Path,
    run_id: str = "run-1",
    *,
    with_manifest: bool = True,
    target_outcome: str = "acquired",
    with_payload: bool = True,
) -> tuple[str, str]:
    paths = resolve_acquisition_paths(artifacts_root=artifacts_root)
    plan_root = _make_plan(artifacts_root)
    proj = project_acquisition_run(plan_root.name, paths=paths)
    actual_run_id = proj.run_id

    content = b"<html>Sample filing content</html>"
    content_sha = sha256_bytes(content)

    db_path = paths.run_state_path(actual_run_id)
    con = sqlite3.connect(db_path)
    if target_outcome == "acquired":
        con.execute(
            "UPDATE target_state SET outcome = 'acquired', selected_sha256 = ?, selected_body_relative_path = ?",
            (content_sha, "bodies/report.htm"),
        )
        op_row = con.execute(
            "SELECT operation_id FROM operation_state WHERE selected = 1"
        ).fetchone()
        if op_row:
            op_id = op_row[0]
            att_id = operation_attempt_id(op_id, 1)
            con.execute(
                "INSERT INTO operation_attempts (attempt_id, operation_id, attempt_number, outcome, retryable, error_code, started_at_utc, finished_at_utc) VALUES (?, ?, 1, 'succeeded', 0, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z')",
                (att_id, op_id),
            )
            con.execute(
                "UPDATE operation_state SET status = 'succeeded', attempt_count = 1, last_attempt_id = ?, error_code = NULL WHERE operation_id = ?",
                (att_id, op_id),
            )
    elif target_outcome == "failed":
        con.execute(
            "UPDATE target_state SET outcome = 'failed', selected_sha256 = NULL, selected_body_relative_path = NULL"
        )
        op_row = con.execute(
            "SELECT operation_id FROM operation_state WHERE selected = 1"
        ).fetchone()
        if op_row:
            op_id = op_row[0]
            att_id = operation_attempt_id(op_id, 1)
            con.execute(
                "INSERT INTO operation_attempts (attempt_id, operation_id, attempt_number, outcome, retryable, error_code, started_at_utc, finished_at_utc) VALUES (?, ?, 1, 'failed', 0, 'failed:processing_error', '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z')",
                (att_id, op_id),
            )
            con.execute(
                "UPDATE operation_state SET status = 'failed', attempt_count = 1, last_attempt_id = ?, error_code = 'failed:processing_error' WHERE operation_id = ?",
                (att_id, op_id),
            )
    else:
        con.execute(
            "UPDATE target_state SET outcome = ?, selected_sha256 = NULL, selected_body_relative_path = NULL",
            (target_outcome,),
        )
    con.commit()
    con.close()

    if with_payload and target_outcome == "acquired":
        staging_body = paths.run_staging_root(actual_run_id) / "bodies/report.htm"
        staging_body.parent.mkdir(parents=True, exist_ok=True)
        staging_body.write_bytes(content)

    if not with_manifest:
        paths.run_manifest_path(actual_run_id).unlink()

    return actual_run_id, content_sha


def test_publish_refuses_when_manifest_missing(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, with_manifest=False)
    with pytest.raises(RunNotPublishableError, match="run manifest is missing"):
        publish_acquisition_run(paths, run_id)


def test_publish_refuses_when_incomplete(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, target_outcome="pending")
    with pytest.raises(RunNotPublishableError, match="is incomplete"):
        publish_acquisition_run(paths, run_id)


def test_publish_refuses_when_error_outcome_without_allow_errors(
    tmp_path: Path,
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, target_outcome="failed", with_payload=False)
    with pytest.raises(RunNotPublishableError, match="allow_errors required"):
        publish_acquisition_run(paths, run_id, allow_errors=False)


def test_publish_refuses_referential_integrity_violation(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, target_outcome="acquired", with_payload=False)
    with pytest.raises(ReferentialIntegrityError, match="missing from payload_index"):
        publish_acquisition_run(paths, run_id)


def test_publish_successful_run_creates_snapshot_and_receipt(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, sha = _setup_run(tmp_path, target_outcome="acquired")

    pub = publish_acquisition_run(paths, run_id, branch_name="main")
    assert pub.status == "published"
    assert pub.snapshot_id is not None
    assert pub.receipt is not None
    assert pub.receipt.adopted_payload_count == 1
    assert pub.receipt.relation_row_counts["target_results"] == 1

    receipt = read_publication_receipt(paths, run_id)
    assert receipt is not None
    assert receipt.snapshot_id == pub.snapshot_id

    repub = publish_acquisition_run(paths, run_id, branch_name="main")
    assert repub.status == "already_published"
    assert repub.snapshot_id == pub.snapshot_id


def test_publish_refuses_stale_branch_tip(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    run_id, _ = _setup_run(tmp_path, target_outcome="acquired")

    with pytest.raises(StaleParentError, match="expected 'non_existent_tip'"):
        publish_acquisition_run(
            paths, run_id, branch_name="main", expected_branch_tip="non_existent_tip"
        )
