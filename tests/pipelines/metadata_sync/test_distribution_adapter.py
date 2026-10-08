"""Tests for metadata sync distribution adapter contract."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.submissions.builder import build_submission_table
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.distribution.partition import build_assignment
from edgar_sec.infra.distribution.receipt import WorkerReceipt
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.metadata_sync.distribution_adapter import (
    MetadataDistributionAdapter,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import Plan, build_plan, write_plan
from tests.support import fixture_cohort


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
    resolved = adapter.resolve_plan(p.plan_id)
    assert resolved.plan_id == p.plan_id
    assert adapter.get_chunk_count(p) == 2
    dest = adapter.default_destination(p.plan_id)
    assert "metadata" in str(dest)


def test_metadata_adapter_export_and_adopt(tmp_path: Path) -> None:
    """Verifies bundle export and adoption cycle."""
    adapter = MetadataDistributionAdapter(artifacts_root=tmp_path)
    p = _make_plan(tmp_path)

    bundle_dir = tmp_path / "bundle_worker_0"
    asgn = build_assignment("metadata", p.plan_id, "w0", (0,))
    adapter.export_worker_bundle(p, asgn, bundle_dir)

    assert (bundle_dir / "plan.json").is_file()
    assert (bundle_dir / "roster").is_dir()

    # Create a valid chunk file in bundle_dir
    chunk_file = bundle_dir / "transient" / p.plan_id / "chunk-0.parquet"
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

    digest = file_sha256(chunk_file)
    rel_path = f"transient/{p.plan_id}/chunk-0.parquet"
    receipt = WorkerReceipt(
        pipeline="metadata",
        plan_id=p.plan_id,
        worker_id="w0",
        completed_chunks=(0,),
        row_count=len(ciks),
        digests={rel_path: digest},
    )

    report = adapter.adopt_worker_bundle(p, bundle_dir, receipt)
    assert report.adopted_chunks == (0,)
