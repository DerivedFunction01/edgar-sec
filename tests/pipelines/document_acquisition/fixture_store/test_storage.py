from __future__ import annotations

import io
import sqlite3

import pytest

from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import open_fixture
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from tests.pipelines.document_acquisition.fixture_store.fixture_helpers import (
    FIXTURE_PLAN_PIN,
    append_test_case,
    initialize_test_fixture,
)


def test_fixture_bodies_are_deduplicated_and_cases_are_run_scoped(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    body = b"same selected parser input"

    first = append_test_case(paths, "fixture-a", "target-a", body)
    repeated = append_test_case(paths, "fixture-a", "target-a", body)
    second = append_test_case(paths, "fixture-a", "target-b", body)

    assert not first.reused
    assert repeated.reused
    assert second.reused
    _, connection = open_fixture(paths, "fixture-a", readonly=True)
    try:
        assert connection.execute("SELECT COUNT(*) FROM body_blobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 2
    finally:
        connection.close()


def test_fixture_body_limit_failure_is_atomic(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    body = b"larger than limit"
    with pytest.raises(FixtureStoreError, match="exceeds max_body_bytes"):
        append_fixture_case(
            paths,
            "fixture-a",
            {
                "capture_id": "capture-1",
                "run_id": "run-1",
                "target_plan_id": FIXTURE_PLAN_PIN.target_plan_id,
                "target_plan_digest": FIXTURE_PLAN_PIN.target_plan_digest,
                "target_plan_schema_version": FIXTURE_PLAN_PIN.target_plan_schema_version,
                "captured_at_utc": "2026-10-14T00:00:00Z",
            },
            {
                "capture_id": "capture-1",
                "target_id": "target-a",
                "attempt_id": "attempt-a",
                "accession": "0000123456-24-000001",
                "form": "4",
                "request_id": "request-a",
                "target_role": "primary",
                "target_type": "primary",
                "source_origin": "inventory_index",
                "retrieval_mode": "direct_url",
                "target_url": None,
                "sequence": None,
                "selected_filename": "form4.htm",
                "body_sha256": "0" * 64,
                "byte_size": len(body),
            },
            io.BytesIO(body),
            max_body_bytes=len(body) - 1,
        )
    _, connection = open_fixture(paths, "fixture-a", readonly=True)
    try:
        assert connection.execute("SELECT COUNT(*) FROM body_blobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
    finally:
        connection.close()


def test_conflicting_case_is_rejected_without_partial_blob_insert(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    append_test_case(paths, "fixture-a", "target-a", b"first")

    with pytest.raises(FixtureStoreError, match="conflicting immutable cases record"):
        append_test_case(paths, "fixture-a", "target-a", b"second")

    _, connection = open_fixture(paths, "fixture-a", readonly=True)
    try:
        assert connection.execute("SELECT COUNT(*) FROM body_blobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
    finally:
        connection.close()


def test_fixture_case_update_is_rejected_by_immutability_trigger(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    append_test_case(paths, "fixture-a", "target-a", b"fixture body")
    _, connection = open_fixture(paths, "fixture-a", readonly=False)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE cases SET selected_filename = 'other.htm' "
                "WHERE capture_id = 'capture-1' AND target_id = 'target-a'"
            )
    finally:
        connection.close()
