"""Tests for metadata sync distribution adapter contract."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.submissions.builder import build_submission_table
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.distribution.cli import cmd_export, cmd_import, cmd_worker
from edgar_sec.infra.distribution.partition import build_assignment
from edgar_sec.infra.distribution.protocol import WorkerFile, WorkerReceipt
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.metadata_sync.distribution_adapter import (
    MetadataDistributionAdapter,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import Plan, build_plan, write_plan
from tests.support import (
    FakeSession,
    build_test_client,
    cik_payload,
    fixture_cohort,
    submissions_document,
)


def _make_plan(tmp_path: Path) -> Plan:
    cohort = fixture_cohort("cik_sec_mini.csv")
    p = build_plan(
        cohort.roster,
        chunk_size=2,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
    )
    paths = resolve_run_paths(p.plan_id, tmp_path)
    write_plan(p, paths)
    return p


def test_metadata_adapter_contract(tmp_path: Path) -> None:
    """Verifies metadata adapter attributes and plan resolution."""
    adapter = MetadataDistributionAdapter(artifacts_root=tmp_path)
    assert adapter.pipeline_name == "metadata"

    p = _make_plan(tmp_path)
    resolved = adapter.resolve_work(p.plan_id)
    assert resolved.plan.plan_id == p.plan_id
    summary = adapter.describe_work(p.plan_id, resolved)
    assert summary.chunk_count == 2
    assert summary.work_digest
    assert any(item.work_id == p.plan_id for item in adapter.list_work_items())
    dest = adapter.default_destination(p.plan_id)
    assert "metadata" in str(dest)


def test_metadata_adapter_export_and_adopt(tmp_path: Path) -> None:
    """Verifies bundle export and adoption cycle."""
    adapter = MetadataDistributionAdapter(artifacts_root=tmp_path)
    p = _make_plan(tmp_path)
    work = adapter.resolve_work(p.plan_id)
    work_digest = adapter.describe_work(p.plan_id, work).work_digest

    bundle_dir = tmp_path / "bundle_worker_0"
    asgn = build_assignment("metadata", p.plan_id, work_digest, "w0", (0,))
    adapter.export_worker_bundle(work, asgn, bundle_dir)

    assert (bundle_dir / "plan.json").is_file()
    assert (bundle_dir / "roster").is_dir()

    # Create a valid chunk file in bundle_dir
    chunk_file = bundle_dir / "chunks" / "chunk_0000.parquet"
    chunk_file.parent.mkdir(parents=True, exist_ok=True)
    ciks = p.chunk_ciks(0)
    fp = p.input_fingerprint
    rows = [
        {
            "cik": cik,
            "status": "ok",
            "input_fingerprint": fp,
            "filings": [],
            "anomalies": [],
        }
        for cik in ciks
    ]
    tbl = build_submission_table(rows)
    write_parquet_table(tbl, chunk_file)

    file_digest = file_sha256(chunk_file)
    receipt = WorkerReceipt(
        pipeline="metadata",
        work_id=p.plan_id,
        work_digest=work_digest,
        assignment_id=asgn.assignment_id,
        worker_id="w0",
        completed_chunks=(0,),
        file_records={
            "chunks/chunk_0000.parquet": WorkerFile(
                chunk_file.stat().st_size, file_digest
            )
        },
        result_metadata={"row_count": len(ciks)},
    )

    report = adapter.adopt_worker_bundle(work, bundle_dir, receipt)
    assert report.adopted_chunks == (0,)


def test_metadata_distribution_lifecycle_offline(tmp_path: Path) -> None:
    cohort = fixture_cohort("cik_sec_mini.csv")
    plan = build_plan(
        cohort.roster,
        chunk_size=2,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
    )
    write_plan(plan, resolve_run_paths(plan.plan_id, tmp_path))
    session = FakeSession()
    for index, cik in enumerate(plan.roster.range_ciks(0, plan.row_count)):
        session.register(submissions_document(cik), cik_payload(cik, f"Issuer {index}"))
    adapter = MetadataDistributionAdapter(
        artifacts_root=tmp_path,
        client_factory=lambda: build_test_client(session),
    )
    destination = tmp_path / "transferred"
    assert (
        cmd_export(adapter, plan.plan_id, worker_count=1, destination=destination) == 0
    )
    bundle = destination / "worker-00"
    assert cmd_worker(adapter, bundle, workers=1) == 0
    assert cmd_import(adapter, plan.plan_id, bundle) == 0
    assert resolve_run_paths(plan.plan_id, tmp_path).chunk_file(0).is_file()
    assert cmd_import(adapter, plan.plan_id, bundle) == 0
