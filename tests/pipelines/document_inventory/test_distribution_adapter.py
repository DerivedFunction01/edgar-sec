"""Tests for document inventory distribution adapter contract."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.distribution.cli import cmd_export, cmd_import, cmd_worker
from edgar_sec.infra.distribution.partition import build_assignment
from edgar_sec.infra.distribution.receipt import RECEIPT_FILE, read_receipt
from edgar_sec.pipelines.document_inventory.distribution_adapter import (
    InventoryDistributionAdapter,
)
from edgar_sec.pipelines.document_inventory.paths import inventory_run_paths
from edgar_sec.pipelines.document_inventory.run_manifest import (
    write_run_manifest,
    write_work_order,
)
from edgar_sec.pipelines.document_inventory.run_state import load_run_status
from edgar_sec.pipelines.document_inventory.snapshot.projection import (
    project_catalog_plan,
)
from edgar_sec.pipelines.filing_catalog.paths import FilingCatalogPaths
from edgar_sec.pipelines.filing_catalog.publication import plan_fingerprint
from tests.support import FakeSession, build_test_http, fixture_path

IDENTITY = {
    "parent_snapshot_id": "snap-1",
    "canonical_cohort_id": "cohort-1",
    "source_identity": "source-1",
    "parser_version": "parser-1",
    "chunk_size": 2,
    "refresh_mode": "normal",
    "fetch_mode": "live",
}


def _items(count: int) -> list[IndexWorkItem]:
    return [
        IndexWorkItem(
            AccessionNumber.from_any(f"{n:010d}26000001"),
            f"https://example.test/{n}-index.htm",
        )
        for n in range(1, count + 1)
    ]


def _prepare_run(tmp_path: Path, run_id: str = "run_123"):
    paths = inventory_run_paths(tmp_path, run_id)
    items = _items(4)
    write_work_order(paths.work_order_path(), items, batch_rows=2)
    manifest = write_run_manifest(
        paths,
        work_order_path=paths.work_order_path(),
        fixture_id=None,
        **IDENTITY,
    )
    return manifest, paths


def _write_catalog_plan(artifacts_root: Path, plan_id: str) -> None:
    table = pq.read_table(fixture_path("catalog/cohort_observations.parquet")).slice(
        0, 1
    )
    root = FilingCatalogPaths(artifacts_root).plan_dir(plan_id)
    root.mkdir(parents=True)
    (root / "selection_report.json").write_text("{}", encoding="utf-8")
    forms = sorted(set(table.column("form").to_pylist()))
    counts = {}
    for form in forms:
        rows = table.filter(pc.equal(table.column("form"), form))
        target = root / "targets" / f"form={form.replace('/', '_')}" / "data.parquet"
        target.parent.mkdir(parents=True)
        pq.write_table(rows, target)
        counts[form] = rows.num_rows
    locator_keys = sorted(set(table.column("document_locator_key").to_pylist()))
    pq.write_table(
        pa.table({"document_locator_key": pa.array(locator_keys, type=pa.string())}),
        root / "locator_groups.parquet",
    )
    payload = {
        "plan_id": plan_id,
        "plan_schema_version": "1.2",
        "catalog_id": "catalog-test",
        "scope": "deterministic",
        "forms": forms,
        "counts": counts,
        "selected_rows": sum(counts.values()),
        "active_targets_count": sum(counts.values()),
        "unique_locators_count": len(locator_keys),
    }
    payload["plan_fingerprint"] = plan_fingerprint(payload, locator_keys)
    (root / "plan.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def resource_profile(tmp_path: Path):
    return derive_resources(
        requested_threads=1,
        cli_overrides={"runtime.temp_directory": str(tmp_path / "duckdb-tmp")},
    )


def test_inventory_adapter_contract(tmp_path: Path) -> None:
    """Verifies inventory work identity, digest, and run discovery."""
    adapter = InventoryDistributionAdapter(artifacts_root=tmp_path)
    assert adapter.pipeline_name == "inventory"

    manifest, paths = _prepare_run(tmp_path)
    work = (manifest, paths)
    summary = adapter.describe_work(manifest.run_id, work)
    assert summary.work_id == manifest.run_id
    assert summary.chunk_count == 2
    assert summary.work_digest
    assert adapter.list_work_items() == ()
    dest = adapter.default_destination(manifest.run_id)
    assert "inventory" in str(dest)

    with pytest.raises(ValueError, match="invalid"):
        adapter.resolve_work(manifest.run_id)


def test_inventory_adapter_export(tmp_path: Path) -> None:
    """Verifies bundle export preserves work order and run manifest."""
    adapter = InventoryDistributionAdapter(artifacts_root=tmp_path)
    manifest, paths = _prepare_run(tmp_path)

    bundle_dir = tmp_path / "bundle_worker_0"
    digest = adapter.describe_work(manifest.run_id, (manifest, paths)).work_digest
    asgn = build_assignment("inventory", manifest.run_id, digest, "w0", (0,))
    adapter.export_worker_bundle((manifest, paths), asgn, bundle_dir)

    assert (bundle_dir / "run_manifest.json").is_file()
    assert (bundle_dir / "work_order.parquet").is_file()


def test_catalog_plan_is_not_projected_by_work_resolution(
    tmp_path: Path,
) -> None:
    _write_catalog_plan(tmp_path, "catalog-plan")
    adapter = InventoryDistributionAdapter(artifacts_root=tmp_path)
    with pytest.raises(ValueError, match="invalid"):
        adapter.resolve_work("catalog-plan")
    assert (
        not inventory_run_paths(tmp_path, "catalog-plan").run_manifest_path().exists()
    )


def test_inventory_distribution_lifecycle_offline(
    tmp_path: Path, resource_profile
) -> None:
    _write_catalog_plan(tmp_path, "catalog-plan")
    projection = project_catalog_plan(
        "catalog-plan", artifacts_root=tmp_path, profile=resource_profile
    )
    session = FakeSession()
    table = pq.read_table(projection.paths.work_order_path())
    index_html = fixture_path("document_inventory_index_page.html").read_bytes()
    for url in table.column("index_url").to_pylist():
        session.register_bytes(url, index_html)
    adapter = InventoryDistributionAdapter(
        artifacts_root=tmp_path,
        http_client=build_test_http(session),
    )
    assert any(item.work_id == projection.run_id for item in adapter.list_work_items())

    destination = tmp_path / "transferred"
    assert (
        cmd_export(
            adapter,
            projection.run_id,
            worker_count=1,
            destination=destination,
        )
        == 0
    )
    bundle = destination / "worker-00"
    assert cmd_worker(adapter, bundle, workers=1) == 0
    receipt = read_receipt(bundle / RECEIPT_FILE)
    assert receipt.completed_chunks == (0,)
    assert receipt.result_metadata["outcome_rows"] == table.num_rows

    assert cmd_import(adapter, projection.run_id, bundle) == 0
    status = load_run_status(tmp_path, projection.run_id)
    assert status.committed_chunks == 1
    assert status.outstanding_chunks == 0
    assert cmd_import(adapter, projection.run_id, bundle) == 0

    output = next(
        path for path in receipt.file_records if path.endswith("entries.parquet")
    )
    (bundle / output).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="file verification failed"):
        cmd_import(adapter, projection.run_id, bundle)
