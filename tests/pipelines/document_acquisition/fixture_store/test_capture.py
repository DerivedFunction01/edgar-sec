from __future__ import annotations

import hashlib
import sqlite3

import pytest

from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    capture_fixture_run,
    create_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    get_fixture_case,
    list_fixture_summaries,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureOperationError,
    FixturePlanPin,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    _materialize_fixture_case,
    list_fixture_cases,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from tests.acquisition_run_fixture import make_acquisition_run
from tests.pipelines.document_acquisition.fixture_store.fixture_helpers import (
    create_test_fixture_for_run,
)


def _mark_acquired(paths, run_id: str, row: dict, body: bytes) -> None:
    target_id = row["target_id"]
    selected_dir = paths.run_staging_root(run_id) / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    selected_path = selected_dir / f"{target_id}.htm"
    selected_path.write_bytes(body)
    relative = selected_path.relative_to(paths.run_dir(run_id)).as_posix()
    digest = hashlib.sha256(body).hexdigest()
    with sqlite3.connect(paths.run_state_path(run_id)) as connection:
        connection.execute(
            "UPDATE target_state SET outcome='acquired', source='live_sec', "
            "attempt_count=1, last_attempt_id=?, source_sha256=?, source_byte_size=?, "
            "source_body_relative_path=NULL, selected_sha256=?, selected_byte_size=?, "
            "selected_body_relative_path=? WHERE target_id=?",
            (
                f"attempt-{target_id}",
                digest,
                len(body),
                digest,
                len(body),
                relative,
                target_id,
            ),
        )
        connection.execute(
            "UPDATE operation_state SET status='pending', error_code=NULL, retryable=0 "
            "WHERE target_id=? AND requested=1 AND selected=1",
            (target_id,),
        )
        connection.execute(
            "INSERT INTO attempts (attempt_id, target_id, attempt_number, attempt_kind, "
            "source, outcome, retryable, error_code, http_status, requested_url, final_url, "
            "started_at_utc, finished_at_utc, source_sha256, source_byte_size, "
            "source_body_relative_path, selected_sha256, selected_byte_size, "
            "selected_body_relative_path, selected_filename) "
            "VALUES (?, ?, 1, 'document_body', 'live_sec', 'acquired', 0, NULL, 200, "
            "?, ?, '2026-10-14T00:00:00Z', '2026-10-14T00:00:01Z', ?, ?, NULL, ?, ?, ?, ?)",
            (
                f"attempt-{target_id}",
                target_id,
                row["target_url"],
                row["target_url"],
                digest,
                len(body),
                digest,
                len(body),
                relative,
                selected_path.name,
            ),
        )


def test_fixture_fill_captures_staged_body_without_raw_response_retention(
    tmp_path,
) -> None:
    paths, run_id, row = make_acquisition_run(tmp_path, lazy=False)
    body = b"<html><body>offline parser input</body></html>"
    _mark_acquired(paths, run_id, row, body)
    create_test_fixture_for_run(paths, "fixture-body", run_id)
    progress = []

    result = capture_fixture_run(
        "fixture-body",
        run_id,
        paths=paths,
        max_body_bytes=1024,
        on_target=lambda current, total: progress.append((current, total)),
    )

    case = get_fixture_case(paths, "fixture-body", result.capture_id, row["target_id"])
    assert result.captured_cases == 1
    assert result.skipped_targets == 0
    assert progress == [(1, 1)]
    assert case.body_sha256 == hashlib.sha256(body).hexdigest()
    assert case.byte_size == len(body)
    assert case.attempt_id == f"attempt-{row['target_id']}"
    output = tmp_path / "materialized.bin"
    _materialize_fixture_case(
        "fixture-body", result.capture_id, row["target_id"], output, paths=paths
    )
    assert output.read_bytes() == body


def test_one_run_capture_groups_all_acquired_target_bodies(tmp_path) -> None:
    paths, run_id, first_row = make_acquisition_run(
        tmp_path, lazy=False, sibling_failure=True
    )
    second_row = dict(first_row)
    second_row.update(target_id="target-2", request_id="request-2")
    first_body = b"<html>first</html>"
    second_body = b"<html>second</html>"
    _mark_acquired(paths, run_id, first_row, first_body)
    _mark_acquired(paths, run_id, second_row, second_body)
    create_test_fixture_for_run(paths, "fixture-run", run_id)

    result = capture_fixture_run(
        "fixture-run", run_id, paths=paths, max_body_bytes=1024
    )

    cases = list(list_fixture_cases(paths, fixture_id="fixture-run"))
    assert result.captured_cases == 2
    assert result.skipped_targets == 0
    assert {case.capture_id for case in cases} == {result.capture_id}
    assert {case.target_id for case in cases} == {"target-1", "target-2"}
    assert list_fixture_summaries(paths)[0].capture_count == 1


def test_fixture_fill_refuses_missing_selected_bytes_and_oversized_bodies(
    tmp_path,
) -> None:
    paths, run_id, row = make_acquisition_run(tmp_path, lazy=False)
    create_test_fixture_for_run(paths, "fixture-empty", run_id)

    with pytest.raises(FixtureOperationError, match="no acquired targets"):
        capture_fixture_run("fixture-empty", run_id, paths=paths, max_body_bytes=1024)

    body = b"larger than cap"
    _mark_acquired(paths, run_id, row, body)
    with pytest.raises(FixtureOperationError, match="exceeds max_body_bytes"):
        capture_fixture_run(
            "fixture-empty", run_id, paths=paths, max_body_bytes=len(body) - 1
        )


def test_fixture_create_pins_published_target_plan(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    fixture = create_fixture(
        "fixture-pin",
        FixturePlanPin("plan-a", "a" * 64, 1),
        paths=paths,
    )

    assert fixture == paths.fixture_paths("fixture-pin").root
