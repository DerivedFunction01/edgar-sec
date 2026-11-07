"""Plan -> run -> checkpoint -> merge -> publish, offline; only HTTP is faked."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.pipelines.metadata_sync.checkpoints import discover_completed_chunks
from edgar_sec.pipelines.metadata_sync.discovery import current_snapshot_id
from edgar_sec.pipelines.metadata_sync.merger import merge_chunks, publish_snapshot
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan, load_plan, write_plan
from edgar_sec.pipelines.metadata_sync.snapshot import resolve_snapshot_parts
from edgar_sec.pipelines.metadata_sync.worker import run_chunk, run_chunk_ids
from tests.support import FakeSession, fixture_cohort, load_fixture


def _plan_for(tmp_path: Path, cohort, chunk_size: int):
    plan = build_plan(
        cohort.roster,
        chunk_size=chunk_size,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
    )
    return plan, resolve_run_paths(plan.plan_id, tmp_path)


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


def _published_rows(metadata, snapshot_id: str) -> list[dict]:
    """Every row of a published snapshot, read through its DAG relation."""
    parts = resolve_snapshot_parts(metadata, snapshot_id)
    rows: list[dict] = []
    for path in parts.paths:
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def test_full_replay_produces_publishable_snapshot(
    client, session: FakeSession, tmp_path: Path
) -> None:
    _seed_session(session)
    cohort = fixture_cohort("cik_sec_mini.csv")
    plan, run_paths = _plan_for(tmp_path, cohort, 2)
    write_plan(plan, run_paths)

    assert discover_completed_chunks(plan, run_paths) == {}

    run_chunk_ids(
        client,
        plan,
        run_paths,
        plan.chunk_ids(),
        snapshot_id=plan.plan_id,
        workers=2,
    )

    completed = discover_completed_chunks(plan, run_paths)
    assert set(completed) == {0, 1}

    report = merge_chunks(plan, run_paths, plan.plan_id)
    assert report.row_count == cohort.row_count == 4
    assert report.chunk_count == 2
    assert report.duplicate_accessions == []

    manifest_payload = publish_snapshot(report, run_paths.metadata)
    assert manifest_payload["row_count"] == 4

    table = pa.Table.from_pylist(
        _published_rows(run_paths.metadata, plan.plan_id),
        schema=SUBMISSION_METADATA_SCHEMA,
    )
    assert table.schema.equals(SUBMISSION_METADATA_SCHEMA, check_metadata=False)
    ciks = table.column("cik").to_pylist()
    assert sorted(ciks) == sorted(cohort.roster.range_ciks(0, cohort.row_count))

    assert current_snapshot_id(run_paths.metadata) == plan.plan_id


def test_bulk_replay_matches_per_cik_rows(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """A bulk-mode replay publishes the same rows as the per-CIK replay."""
    import zipfile

    from edgar_sec.pipelines.metadata_sync.sec_client import (
        BulkSubmissionsArchive,
        BulkSubmissionsClient,
    )

    _seed_session(session)
    cohort = fixture_cohort("cik_sec_mini.csv")

    plan_a, paths_a = _plan_for(tmp_path / "live", cohort, 2)
    write_plan(plan_a, paths_a)
    run_chunk_ids(
        client,
        plan_a,
        paths_a,
        plan_a.chunk_ids(),
        snapshot_id=plan_a.plan_id,
        workers=2,
    )
    publish_snapshot(merge_chunks(plan_a, paths_a, plan_a.plan_id), paths_a.metadata)
    rows_a = {
        row["cik"]: row for row in _published_rows(paths_a.metadata, plan_a.plan_id)
    }

    members: dict[str, bytes] = {
        f"CIK{FORD}.json": json.dumps(load_fixture("recent_submissions.json")).encode(),
        FORD_HIST: json.dumps(load_fixture("historical_submissions.json")).encode(),
    }
    for cik in ("0000001985", "0000001761", "0000000020"):
        members[f"CIK{cik}.json"] = json.dumps(
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
            }
        ).encode()
    zip_path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    bulk_client = BulkSubmissionsClient(BulkSubmissionsArchive(zip_path))

    plan_b, paths_b = _plan_for(tmp_path / "bulk", cohort, 2)
    write_plan(plan_b, paths_b)
    run_chunk_ids(
        bulk_client,
        plan_b,
        paths_b,
        plan_b.chunk_ids(),
        snapshot_id=plan_b.plan_id,
        workers=2,
    )
    publish_snapshot(merge_chunks(plan_b, paths_b, plan_b.plan_id), paths_b.metadata)
    rows_b = {
        row["cik"]: row for row in _published_rows(paths_b.metadata, plan_b.plan_id)
    }

    assert set(rows_b) == set(rows_a)
    for cik, live_row in rows_a.items():
        bulk_row = rows_b[cik]
        assert bulk_row["status"] == live_row["status"]
        strip = lambda rows: [  # noqa: E731
            {k: v for k, v in row.items() if k != "source_file"} for row in rows
        ]
        assert strip(bulk_row["filings"]) == strip(live_row["filings"])
        assert bulk_row["historical_files_total"] == live_row["historical_files_total"]


def _payload(cik: str, *accessions: str) -> bytes:
    return json.dumps(
        {
            "name": f"COMPANY {cik}",
            "filings": {
                "recent": {
                    "accessionNumber": list(accessions),
                    "filingDate": ["2026-01-02"] * len(accessions),
                    "form": ["10-K"] * len(accessions),
                    "size": [1024] * len(accessions),
                },
                "files": [],
            },
        }
    ).encode()


def _store_archive(store, members: dict[str, bytes], tmp_path: Path, name: str):
    import zipfile

    zip_path = tmp_path / name
    with zipfile.ZipFile(zip_path, "w") as archive:
        for member, payload in members.items():
            archive.writestr(member, payload)
    return store.put_file(
        "submissions_bulk",
        zip_path,
        source_url=(
            "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
        ),
    )


def test_archive_baseline_carry_forward(tmp_path: Path, capsys) -> None:
    """A second archive reprocesses exactly the CIKs whose members changed."""
    from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
    from edgar_sec.pipelines.metadata_sync.commands.plan import cmd_plan
    from edgar_sec.pipelines.metadata_sync.commands.run import cmd_run
    from edgar_sec.pipelines.metadata_sync.options import plan_options, run_options
    from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
    from edgar_sec.pipelines.metadata_sync.planner import member_fingerprints

    ciks = ["0000000020", "0000001761", "0000001985", "0000037996"]
    metadata = resolve_metadata_paths(tmp_path)
    store = BulkArchiveStore(metadata.bulk_archives_root)
    members_v1 = {f"CIK{cik}.json": _payload(cik, f"{cik}-26-000001") for cik in ciks}
    members_v1["CIK0000001985-submissions-001.json"] = b"{}"
    reference_v1 = _store_archive(store, members_v1, tmp_path, "v1.zip")

    def _planned_ids() -> set[str]:
        return {path.name for path in metadata.plans_root.iterdir() if path.is_dir()}

    assert (
        cmd_plan(plan_options(from_archive=True, artifacts_root=tmp_path, chunk_size=2))
        == 0
    )
    (plan_v1,) = _planned_ids()
    assert cmd_run(run_options(plan_id=plan_v1, artifacts_root=tmp_path)) == 0
    plan_v1_obj, paths_v1 = (
        load_plan(resolve_run_paths(plan_v1, tmp_path)),
        resolve_run_paths(plan_v1, tmp_path),
    )
    publish_snapshot(merge_chunks(plan_v1_obj, paths_v1, plan_v1), metadata)
    rows_v1 = {row["cik"]: row for row in _published_rows(metadata, plan_v1)}

    members_v2 = dict(members_v1)
    members_v2["CIK0000001761.json"] = _payload(
        "0000001761", "0000001761-26-000001", "0000001761-26-000002"
    )
    members_v2["CIK0000001985-submissions-001.json"] = b'{"changed": true}'
    reference_v2 = _store_archive(store, members_v2, tmp_path, "v2.zip")
    assert reference_v2.sha256 != reference_v1.sha256

    fingerprints_v1 = member_fingerprints(store.member_index(reference_v1))
    fingerprints_v2 = member_fingerprints(store.member_index(reference_v2))
    changed_ciks = {cik for cik in ciks if fingerprints_v1[cik] != fingerprints_v2[cik]}
    assert changed_ciks == {"0000001761", "0000001985"}

    assert (
        cmd_plan(plan_options(from_archive=True, artifacts_root=tmp_path, chunk_size=2))
        == 0
    )
    (plan_v2,) = _planned_ids() - {plan_v1}
    capsys.readouterr()
    assert (
        cmd_run(
            run_options(
                plan_id=plan_v2,
                artifacts_root=tmp_path,
                carry_from_snapshot=plan_v1,
            )
        )
        == 0
    )
    summary = capsys.readouterr().out
    assert "carried_rows" in summary and "normalized_rows" in summary
    carried_line = next(line for line in summary.splitlines() if "carried_rows" in line)
    normalized_line = next(
        line for line in summary.splitlines() if "normalized_rows" in line
    )
    assert carried_line.rsplit(" ", 1)[-1] == "2"
    assert normalized_line.rsplit(" ", 1)[-1] == "2"

    plan_v2_obj = load_plan(resolve_run_paths(plan_v2, tmp_path))
    paths_v2 = resolve_run_paths(plan_v2, tmp_path)
    publish_snapshot(merge_chunks(plan_v2_obj, paths_v2, plan_v2), metadata)
    rows_v2 = {row["cik"]: row for row in _published_rows(metadata, plan_v2)}

    provenance = {"snapshot_id", "fetched_at"}
    for cik in ("0000000020", "0000037996"):
        before = {k: v for k, v in rows_v1[cik].items() if k not in provenance}
        after = {k: v for k, v in rows_v2[cik].items() if k not in provenance}
        assert after == before
    assert len(rows_v2["0000001761"]["filings"]) == 2


def test_archive_baseline_lineage_and_cohort_augment(
    client, session: FakeSession, tmp_path: Path
) -> None:
    """A baseline publishes in parallel with archive lineage; augments compose."""
    from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
    from edgar_sec.infra.storage.dag.catalog import DAGCatalog
    from edgar_sec.pipelines.metadata_sync.augmentation import augment
    from edgar_sec.pipelines.metadata_sync.commands.plan import cmd_plan
    from edgar_sec.pipelines.metadata_sync.commands.run import cmd_run
    from edgar_sec.pipelines.metadata_sync.discovery import current_snapshot_id
    from edgar_sec.pipelines.metadata_sync.options import plan_options, run_options
    from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
    from tests.support import roster_of

    ciks = ["0000000020", "0000001761", "0000001985", "0000037996"]
    metadata = resolve_metadata_paths(tmp_path)
    store = BulkArchiveStore(metadata.bulk_archives_root)
    members = {f"CIK{cik}.json": _payload(cik, f"{cik}-26-000001") for cik in ciks}
    reference = _store_archive(store, members, tmp_path, "baseline.zip")

    assert (
        cmd_plan(plan_options(from_archive=True, artifacts_root=tmp_path, chunk_size=2))
        == 0
    )
    (plan_id,) = {path.name for path in metadata.plans_root.iterdir() if path.is_dir()}
    assert cmd_run(run_options(plan_id=plan_id, artifacts_root=tmp_path)) == 0
    plan = load_plan(resolve_run_paths(plan_id, tmp_path))
    run_paths = resolve_run_paths(plan_id, tmp_path)
    report = merge_chunks(
        plan, run_paths, plan_id, lineage={"prior_snapshot_id": "cohort-base"}
    )
    publish_snapshot(report, metadata, branch_name="baseline")

    catalog = DAGCatalog(metadata.snapshots_root)
    manifest = catalog.get_manifest(plan_id)
    assert manifest is not None
    assert manifest.kind == "checkpoint" and manifest.parents == ()
    assert manifest.metadata["archive_source_id"] == "submissions_bulk"
    assert manifest.metadata["archive_sha256"] == reference.sha256
    assert manifest.metadata["prior_snapshot_id"] == "cohort-base"
    assert current_snapshot_id(metadata) == ""

    extra = "0000005555"
    session.register(
        submissions_url(extra),
        {
            "name": "EXTRA CO",
            "filings": {
                "recent": {
                    "accessionNumber": [f"{extra}-26-000001"],
                    "filingDate": ["2026-01-02"],
                    "form": ["10-K"],
                    "size": [1024],
                },
                "files": [],
            },
        },
    )
    result = augment(
        client,
        roster_of([*ciks, extra]),
        metadata,
        base_snapshot_id=plan_id,
        new_snapshot_id="augmented",
        chunk_size=2,
        workers=2,
    )
    assert result.base_row_count == 4
    assert result.delta_row_count == 1
    assert result.total_row_count == 5
    rows = _published_rows(metadata, "augmented")
    assert {row["cik"] for row in rows} == {*ciks, extra}


def test_replay_is_resumable_and_does_not_refetch(
    client, session: FakeSession, tmp_path: Path
) -> None:
    _seed_session(session)
    cohort = fixture_cohort("cik_sec_mini.csv")
    plan, run_paths = _plan_for(tmp_path, cohort, 2)
    write_plan(plan, run_paths)

    run_chunk(client, plan, run_paths, 0, snapshot_id=plan.plan_id, workers=2)
    calls_after_first_chunk = len(session.calls)
    assert calls_after_first_chunk > 0

    completed = discover_completed_chunks(plan, run_paths)
    assert set(completed) == {0}

    run_chunk(client, plan, run_paths, 0, snapshot_id=plan.plan_id, workers=2)
    assert len(session.calls) == calls_after_first_chunk

    skipped = run_chunk(client, plan, run_paths, 0, snapshot_id=plan.plan_id, workers=2)
    assert skipped.skipped_existing is True
    assert skipped.row_count == 2
    assert len(session.calls) == calls_after_first_chunk

    run_chunk(client, plan, run_paths, 1, snapshot_id=plan.plan_id, workers=2)
    report = merge_chunks(plan, run_paths, plan.plan_id)
    assert report.row_count == 4


def test_ford_row_preserves_oracle_shape(
    client, session: FakeSession, tmp_path: Path
) -> None:
    _seed_session(session)
    cohort = fixture_cohort("cik_sec_mini.csv")
    plan, run_paths = _plan_for(tmp_path, cohort, 4)
    write_plan(plan, run_paths)
    run_chunk(client, plan, run_paths, 0, snapshot_id=plan.plan_id, workers=2)

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
