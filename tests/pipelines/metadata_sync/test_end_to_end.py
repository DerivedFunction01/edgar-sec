"""End-to-end pipeline replay, offline via a scripted transport.

Exercises the full plan -> run -> checkpoint -> merge -> publish chain over the
committed mini manifest. The only substitution is the HTTP transport; the
planner, worker, checkpoint validation, and DuckDB merge are the real ones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.pipelines.metadata_sync.checkpoints import discover_completed_chunks
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.merger import merge_chunks, publish_snapshot
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from edgar_sec.pipelines.metadata_sync.worker import run_chunk
from tests.support import FakeSession, fixture_path, load_fixture

FORD = "0000037996"
FORD_HIST = "CIK0000037996-submissions-001.json"
FORD_HIST_URL = f"https://data.sec.gov/submissions/{FORD_HIST}"


def _seed_session(session: FakeSession) -> None:
    session.register(submissions_url(FORD), load_fixture("recent_submissions.json"))
    session.register(FORD_HIST_URL, load_fixture("historical_submissions.json"))
    for cik in ("0000001985", "0000001761", "0000000020"):
        session.register(
            submissions_url(cik),
            {
                "name": f"COMPANY {cik}",
                "filings": {
                    "recent": {
                        "accessionNumber": [f"{cik}-26-000001"],
                        "filingDate": ["2026-01-02"],
                        "form": ["10-K"],
                        "size": [1024],
                    },
                    "files": [],
                },
            },
        )


def test_full_replay_produces_publishable_snapshot(
    client, session: FakeSession, tmp_path: Path
) -> None:
    _seed_session(session)
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = build_plan(manifest, chunk_size=2, partition_count=1)
    run_paths = resolve_run_paths(plan["plan_id"], tmp_path)
    write_plan(plan, run_paths)

    assert discover_completed_chunks(plan, run_paths) == {}

    for chunk in plan["chunks"]:
        run_chunk(
            client,
            plan,
            run_paths,
            int(chunk["chunk_id"]),
            snapshot_id=plan["plan_id"],
            workers=2,
        )

    completed = discover_completed_chunks(plan, run_paths)
    assert set(completed) == {0, 1}

    report = merge_chunks(plan, run_paths, plan["plan_id"])
    assert report.row_count == manifest.row_count == 4
    assert report.chunk_count == 2
    assert report.duplicate_accessions == []

    manifest_payload = publish_snapshot(report, run_paths.metadata)
    assert manifest_payload["row_count"] == 4

    table = pq.read_table(run_paths.metadata.snapshot_file(plan["plan_id"]))
    assert table.schema.equals(SUBMISSION_METADATA_SCHEMA, check_metadata=False)
    ciks = table.column("cik").to_pylist()
    assert ciks == sorted(ciks)
    assert ciks == sorted(manifest.ciks)

    pointer = json.loads(run_paths.metadata.current_pointer.read_text())
    assert pointer["snapshot_id"] == plan["plan_id"]
    assert pointer["row_count"] == 4


def test_replay_is_resumable_and_does_not_refetch(
    client, session: FakeSession, tmp_path: Path
) -> None:
    _seed_session(session)
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = build_plan(manifest, chunk_size=2, partition_count=1)
    run_paths = resolve_run_paths(plan["plan_id"], tmp_path)
    write_plan(plan, run_paths)

    run_chunk(client, plan, run_paths, 0, snapshot_id=plan["plan_id"], workers=2)
    calls_after_first_chunk = len(session.calls)
    assert calls_after_first_chunk > 0

    completed = discover_completed_chunks(plan, run_paths)
    assert set(completed) == {0}

    run_chunk(client, plan, run_paths, 0, snapshot_id=plan["plan_id"], workers=2)
    assert len(session.calls) == calls_after_first_chunk

    skipped = run_chunk(
        client, plan, run_paths, 0, snapshot_id=plan["plan_id"], workers=2
    )
    assert skipped.skipped_existing is True
    assert skipped.row_count == 2
    assert len(session.calls) == calls_after_first_chunk

    run_chunk(client, plan, run_paths, 1, snapshot_id=plan["plan_id"], workers=2)
    report = merge_chunks(plan, run_paths, plan["plan_id"])
    assert report.row_count == 4


def test_ford_row_preserves_oracle_shape(
    client, session: FakeSession, tmp_path: Path
) -> None:
    _seed_session(session)
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = build_plan(manifest, chunk_size=4, partition_count=1)
    run_paths = resolve_run_paths(plan["plan_id"], tmp_path)
    write_plan(plan, run_paths)
    run_chunk(client, plan, run_paths, 0, snapshot_id=plan["plan_id"], workers=2)

    table = pq.read_table(run_paths.chunk_file(0))
    row = next(record for record in table.to_pylist() if record["cik"] == FORD)
    assert row["status"] == "ok"
    assert row["identity"]["name"] == "FORD MOTOR CO"
    assert [f["accession_number"] for f in row["filings"]] == [
        "0000037996-26-000039",
        "0000037996-26-000031",
        "0000037996-08-000010",
        "0000037996-08-000004",
    ]
    assert row["filings"][0]["archive_url"] == (
        "https://www.sec.gov/Archives/edgar/data/37996/"
        "000003799626000039/f-20251231.htm"
    )
    assert row["historical_records_total"] == 3
    assert row["contact"]["website"] == ""
