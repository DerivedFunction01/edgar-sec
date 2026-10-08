"""Submissions client fan-out and worker chunk execution tests (offline)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan
from edgar_sec.pipelines.metadata_sync.roster import RosterError
from edgar_sec.pipelines.metadata_sync.sec_client import (
    CikFetchResult,
    SubmissionsClient,
)
from edgar_sec.pipelines.metadata_sync.worker import (
    normalize_one_cik,
    run_chunk,
    run_chunk_ids,
)
from tests.support import FakeSession, compiled_cohort, load_fixture

FORD = "0000037996"
CHUNK_ONE_FIRST = "0000001985"
HIST_NAME = "CIK0000037996-submissions-001.json"
HIST_URL = f"https://data.sec.gov/submissions/{HIST_NAME}"


def _ford_pair(session: FakeSession) -> None:
    session.register(submissions_url(FORD), load_fixture("recent_submissions.json"))
    session.register(HIST_URL, load_fixture("historical_submissions.json"))


def _plan(tmp_path: Path, chunk_size: int = 2):
    cohort = compiled_cohort("cik_sec_mini.csv", tmp_path)
    plan = build_plan(
        cohort.roster,
        chunk_size=chunk_size,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
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


def test_run_chunk_writes_checkpoint_with_all_ciks(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """Rows land in fetch-completion order, so only membership is stable."""
    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)
    session.register(
        submissions_url(CHUNK_ONE_FIRST),
        {"name": "ACCEL INTERNATIONAL CORP", "filings": {"recent": {}, "files": []}},
    )

    result = run_chunk(client, plan, run_paths, 1, snapshot_id="snap1", workers=2)
    assert result.row_count == 2

    path = run_paths.chunk_file(1)
    assert path.is_file()
    table = pq.read_table(path)
    assert set(table.column("cik").to_pylist()) == {CHUNK_ONE_FIRST, FORD}
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
        submissions_url(CHUNK_ONE_FIRST),
        {"name": "ACCEL INTERNATIONAL CORP", "filings": {"recent": {}, "files": []}},
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
    assert len(events) == 2
    assert {e["cik"] for e in events} == {CHUNK_ONE_FIRST, FORD}
    assert all(e["type"] == "cik_normalized" for e in events)
    assert all(e["status"] == "ok" for e in events)


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


def test_run_chunk_resumes_from_partial_staging_file(
    client, session: FakeSession, tmp_path: Path
) -> None:
    from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
    from edgar_sec.engine.submissions.builder import build_submission_table
    from edgar_sec.infra.storage.parquet import StagedParquetWriter

    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)
    session.register(
        submissions_url(CHUNK_ONE_FIRST),
        {"name": "ACCEL INTERNATIONAL CORP", "filings": {"recent": {}, "files": []}},
    )

    row, _ = normalize_one_cik(
        client,
        CHUNK_ONE_FIRST,
        input_name=plan.input_name,
        snapshot_id="snap1",
        input_fingerprint=plan.input_fingerprint,
        chunk_id=1,
    )
    chunk_path = run_paths.chunk_file(1)
    with StagedParquetWriter(
        chunk_path, schema=SUBMISSION_METADATA_SCHEMA, id_column="cik"
    ) as writer:
        writer.write_batch(build_submission_table([row]))

    calls_before = len(session.calls)
    assert calls_before == 1
    assert chunk_path.with_name(f"{chunk_path.name}.tmp").is_file()

    result = run_chunk(client, plan, run_paths, 1, snapshot_id="snap1", workers=2)
    assert result.row_count == 2
    assert result.statuses == {"ok": 2}
    assert result.historical_files == 1
    assert chunk_path.is_file()
    assert not chunk_path.with_name(f"{chunk_path.name}.tmp").exists()

    assert len(session.calls) == calls_before + 2
    table = pq.read_table(chunk_path)
    assert set(table.column("cik").to_pylist()) == {CHUNK_ONE_FIRST, FORD}


def test_run_chunk_resumes_when_all_ciks_already_staged(
    client, session: FakeSession, tmp_path: Path
) -> None:
    from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
    from edgar_sec.engine.submissions.builder import build_submission_table
    from edgar_sec.infra.storage.parquet import StagedParquetWriter

    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)
    session.register(
        submissions_url(CHUNK_ONE_FIRST),
        {"name": "ACCEL INTERNATIONAL CORP", "filings": {"recent": {}, "files": []}},
    )

    row_first, _ = normalize_one_cik(
        client,
        CHUNK_ONE_FIRST,
        input_name=plan.input_name,
        snapshot_id="snap1",
        input_fingerprint=plan.input_fingerprint,
        chunk_id=1,
    )
    row_ford, _ = normalize_one_cik(
        client,
        FORD,
        input_name=plan.input_name,
        snapshot_id="snap1",
        input_fingerprint=plan.input_fingerprint,
        chunk_id=1,
    )
    chunk_path = run_paths.chunk_file(1)
    with StagedParquetWriter(
        chunk_path, schema=SUBMISSION_METADATA_SCHEMA, id_column="cik"
    ) as writer:
        writer.write_batch(build_submission_table([row_first, row_ford]))

    assert chunk_path.with_name(f"{chunk_path.name}.tmp").is_file()
    calls_before = len(session.calls)

    result = run_chunk(client, plan, run_paths, 1, snapshot_id="snap1", workers=2)
    assert result.row_count == 2
    assert result.statuses == {"ok": 2}
    assert result.historical_files == 1
    assert chunk_path.is_file()
    assert not chunk_path.with_name(f"{chunk_path.name}.tmp").exists()
    assert len(session.calls) == calls_before


class _CrashingClient:
    """A submissions client that crashes once for one CIK, then recovers."""

    def __init__(self, inner: SubmissionsClient, crash_cik: str) -> None:
        self._inner = inner
        self._crash_cik = crash_cik
        self._armed = True

    def fetch_cik(self, cik_padded: str) -> CikFetchResult:
        if self._armed and cik_padded == self._crash_cik:
            self._armed = False
            raise RuntimeError("simulated worker crash")
        return self._inner.fetch_cik(cik_padded)


def test_run_chunk_resumes_a_stage_it_wrote_itself(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """A mid-chunk crash keeps the rows already normalized, so a resume
    refetches only the missing CIK instead of the whole chunk."""
    plan, run_paths = _plan(tmp_path, chunk_size=2)
    _ford_pair(session)
    session.register(
        submissions_url(CHUNK_ONE_FIRST),
        {"name": "ACCEL INTERNATIONAL CORP", "filings": {"recent": {}, "files": []}},
    )

    crashing = _CrashingClient(client, FORD)
    with pytest.raises(RuntimeError, match="simulated worker crash"):
        # One worker serializes the chunk, so its first CIK is staged before FORD
        # crashes; the stage is preserved rather than discarded.
        run_chunk(crashing, plan, run_paths, 1, snapshot_id="snap1", workers=1)

    chunk_path = run_paths.chunk_file(1)
    staged = chunk_path.with_name(f"{chunk_path.name}.tmp")
    assert staged.is_file()
    assert set(pq.read_table(staged).column("cik").to_pylist()) == {CHUNK_ONE_FIRST}

    first_calls = session.calls.count(submissions_url(CHUNK_ONE_FIRST))
    ford_calls = session.calls.count(submissions_url(FORD))
    assert first_calls == 1
    assert ford_calls == 0

    result = run_chunk(client, plan, run_paths, 1, snapshot_id="snap1", workers=2)
    assert result.row_count == 2
    assert result.statuses == {"ok": 2}
    assert chunk_path.is_file()
    assert not staged.exists()
    assert set(pq.read_table(chunk_path).column("cik").to_pylist()) == {
        CHUNK_ONE_FIRST,
        FORD,
    }
    # The first CIK was already staged, so only FORD was fetched on resume.
    assert session.calls.count(submissions_url(CHUNK_ONE_FIRST)) == first_calls
    assert session.calls.count(submissions_url(FORD)) == ford_calls + 1
