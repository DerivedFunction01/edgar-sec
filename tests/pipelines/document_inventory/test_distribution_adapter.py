"""Tests for document inventory distribution adapter contract."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.infra.distribution.partition import build_assignment
from edgar_sec.infra.distribution.receipt import WorkerReceipt
from edgar_sec.pipelines.document_inventory.distribution_adapter import (
    InventoryDistributionAdapter,
)
from edgar_sec.pipelines.document_inventory.paths import inventory_run_paths
from edgar_sec.pipelines.document_inventory.run_manifest import (
    write_run_manifest,
    write_work_order,
)

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


def test_inventory_adapter_contract(tmp_path: Path) -> None:
    """Verifies inventory adapter attributes and plan resolution."""
    adapter = InventoryDistributionAdapter(artifacts_root=tmp_path)
    assert adapter.pipeline_name == "inventory"

    manifest, paths = _prepare_run(tmp_path)
    resolved_manifest, resolved_paths = adapter.resolve_plan(manifest.run_id)
    assert resolved_manifest.run_id == manifest.run_id
    assert adapter.get_chunk_count((resolved_manifest, resolved_paths)) == 2
    dest = adapter.default_destination(manifest.run_id)
    assert "inventory" in str(dest)


def test_inventory_adapter_export(tmp_path: Path) -> None:
    """Verifies bundle export preserves work order and run manifest."""
    adapter = InventoryDistributionAdapter(artifacts_root=tmp_path)
    manifest, paths = _prepare_run(tmp_path)

    bundle_dir = tmp_path / "bundle_worker_0"
    asgn = build_assignment("inventory", manifest.run_id, "w0", (0,))
    adapter.export_worker_bundle((manifest, paths), asgn, bundle_dir)

    assert (bundle_dir / "run_manifest.json").is_file()
    assert (bundle_dir / "work_order.parquet").is_file()
