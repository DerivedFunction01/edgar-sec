"""Submissions client fan-out and worker chunk execution tests (offline)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan
from edgar_sec.pipelines.metadata_sync.roster import RosterError, roster_from_manifest
from edgar_sec.pipelines.metadata_sync.worker import (
    normalize_one_cik,
    run_chunk,
    run_chunk_ids,
)
from tests.support import FakeSession, fixture_path, load_fixture

FORD = "0000037996"
SMALL = "0000000020"
HIST_NAME = "CIK0000037996-submissions-001.json"
HIST_URL = f"https://data.sec.gov/submissions/{HIST_NAME}"


def _ford_pair(session: FakeSession) -> None:
    session.register(submissions_url(FORD), load_fixture("recent_submissions.json"))
    session.register(HIST_URL, load_fixture("historical_submissions.json"))


def _plan(tmp_path: Path, chunk_size: int = 2):
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = build_plan(
        roster_from_manifest(manifest),
        chunk_size=chunk_size,
        input_name=manifest.input_name,
        input_fingerprint=manifest.input_fingerprint,
    )
    return plan, resolve_run_paths(plan.plan_id, tmp_path)


# ----------------------------------------------------------------- sec_client


def test_fetch_cik_returns_provenance(client, session: FakeSession) -> None:
    _ford_pair(session)
    result = client.fetch_cik(FORD)

    assert result.fetched_ok is True
    assert result.payload["name"] == "FORD MOTOR CO"
    assert result.byte_count > 0
    assert len(result.response_sha256) == 64
    assert result.historical_files_fetched == 1
    assert result.historical_payloads[0][1] == HIST_NAME
    assert result.terminal_error() is None


def test_fetch_cik_records_permanent_404(client, session: FakeSession) -> None:
    result = client.fetch_cik("0000009999")
    assert result.fetched_ok is False
    assert result.payload is None
    assert result.permanent_error is not None
    assert "404" in result.permanent_error


def test_fetch_cik_records_historical_failure(client, session: FakeSession) -> None:
    recent = load_fixture("recent_submissions.json")
    session.register(submissions_url(FORD), recent)
    result = client.fetch_cik(FORD)

    assert result.fetched_ok is True
    assert result.historical_files_fetched == 0
    assert len(result.historical_errors) == 1
    assert HIST_NAME in result.historical_errors[0]


# --------------------------------------------------------------------- worker


def test_normalize_one_cik_produces_canonical_row(client, session: FakeSession) -> None:
    _ford_pair(session)
    row, result = normalize_one_cik(
        client,
        FORD,
        input_name="cik_sec_mini.csv",
        snapshot_id="snap1",
        input_fingerprint="abc123",
        chunk_id=3,
        fetched_at="2026-01-01T00:00:00Z",
    )

    assert row["status"] == "ok"
    assert row["cik"] == FORD
    assert row["chunk_id"] == 3
    assert row["input_fingerprint"] == "abc123"
    assert row["fetched_at"] == "2026-01-01T00:00:00Z"
    assert row["response_sha256"] == result.response_sha256
    assert row["byte_count"] == result.byte_count
    assert len(row["filings"]) == 4
    assert row["historical_records_total"] == 3


def test_normalize_one_cik_marks_permanent_failure_terminal(
    client, session: FakeSession
) -> None:
    row, _ = normalize_one_cik(
        client,
        "0000009999",
        input_name="x.csv",
        snapshot_id="snap1",
        input_fingerprint="abc",
        chunk_id=0,
    )
    assert row["status"] == "failed"
    assert row["error"]


def test_normalize_one_cik_partial_when_history_fails(
    client, session: FakeSession
) -> None:
    session.register(submissions_url(FORD), load_fixture("recent_submissions.json"))
    row, _ = normalize_one_cik(
        client,
        FORD,
        input_name="x.csv",
        snapshot_id="snap1",
        input_fingerprint="abc",
        chunk_id=0,
    )
    assert row["status"] == "partial"
    assert row["filings"]


def test_run_chunk_writes_checkpoint_in_plan_order(
    client, session: FakeSession, tmp_path: Path
) -> None:
    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)
    session.register(
        submissions_url(SMALL),
        {"name": "SMALL CO", "filings": {"recent": {}, "files": []}},
    )

    result = run_chunk(client, plan, run_paths, 1, snapshot_id="snap1", workers=2)
    assert result.row_count == 2

    path = run_paths.chunk_file(1)
    assert path.is_file()
    table = pq.read_table(path)
    assert table.column("cik").to_pylist() == ["0000000020", FORD]
    assert set(table.column("status").to_pylist()) == {"ok"}
    assert result.statuses == {"ok": 2}


def test_run_chunk_emits_one_row_per_requested_cik_even_on_failure(
    client, session: FakeSession, tmp_path: Path
) -> None:
    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)

    result = run_chunk(client, plan, run_paths, 1, snapshot_id="snap1", workers=2)
    statuses = set(pq.read_table(run_paths.chunk_file(1)).column("status").to_pylist())
    assert result.row_count == 2
    assert statuses == {"ok", "failed"}


def test_run_chunk_rejects_unknown_chunk_id(client, tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    with pytest.raises(RosterError, match="not present in plan"):
        run_chunk(client, plan, run_paths, 99, snapshot_id="snap1")


def test_run_chunk_records_progress_events(
    client, session: FakeSession, tmp_path: Path
) -> None:
    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)
    session.register(
        submissions_url(SMALL),
        {"name": "SMALL CO", "filings": {"recent": {}, "files": []}},
    )
    events: list[dict] = []
    run_chunk(
        client,
        plan,
        run_paths,
        1,
        snapshot_id="snap1",
        workers=2,
        progress=events.append,
    )
    assert [e["cik"] for e in events] == ["0000000020", FORD]
    assert all(e["type"] == "cik_normalized" for e in events)


def test_run_chunk_ids_runs_only_the_chunks_it_is_given(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """A worker's scope comes from its assignment, not from the whole plan."""
    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)
    session.register(
        submissions_url("0000001985"),
        {"name": "A", "filings": {"recent": {}, "files": []}},
    )
    session.register(
        submissions_url("0000001761"),
        {"name": "B", "filings": {"recent": {}, "files": []}},
    )

    results = run_chunk_ids(
        client, plan, run_paths, [1], snapshot_id="snap1", workers=2
    )
    assert [result.chunk_id for result in results] == [1]
    assert run_paths.chunk_file(0).exists() is False


def test_run_chunk_ids_skips_chunks_already_marked_complete(
    client, session: FakeSession, tmp_path: Path
) -> None:
    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)
    first = run_chunk_ids(client, plan, run_paths, [1], snapshot_id="snap1", workers=2)
    assert first[0].skipped_existing is False
    calls = len(session.calls)

    second = run_chunk_ids(client, plan, run_paths, [1], snapshot_id="snap1", workers=2)
    assert second[0].skipped_existing is True
    assert len(session.calls) == calls


def test_run_chunk_ids_never_refetches_a_valid_checkpoint(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """The never-refetch guarantee survives the move to an explicit chunk list."""
    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)
    run_chunk_ids(client, plan, run_paths, [1], snapshot_id="snap1", workers=2)
    calls = len(session.calls)

    run_chunk_ids(client, plan, run_paths, [1], snapshot_id="snap1", workers=2)
    assert len(session.calls) == calls
