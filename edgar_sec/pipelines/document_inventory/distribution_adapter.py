"""Distribution adapter for the document inventory pipeline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import distribution_root, resolve_paths
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.infra.distribution.guards import read_bundle_manifest
from edgar_sec.infra.distribution.protocol import (
    ImportReport,
    WorkerAssignment,
    WorkerReceipt,
)
from edgar_sec.infra.distribution.receipt import build_worker_receipt
from edgar_sec.pipelines.document_inventory.checkpoint import (
    validate_committed_chunk,
)
from edgar_sec.pipelines.document_inventory.coordinator import (
    _cooperative_stop,
    _manifest_kwargs,
    _run_pending,
)
from edgar_sec.pipelines.document_inventory.paths import (
    InventoryRunPaths,
    inventory_run_paths,
)
from edgar_sec.pipelines.document_inventory.run_manifest import (
    InventoryRunManifest,
    iter_work_order_chunks,
    read_run_manifest,
    write_run_manifest,
)
from edgar_sec.pipelines.document_inventory.snapshot.builder import (
    _effective_chunk_size,
    _run_identity,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection import (
    project_catalog_plan,
)


class InventoryDistributionAdapter:
    """Distribution adapter for the document inventory pipeline."""

    pipeline_name = "inventory"

    def __init__(self, artifacts_root: Path | None = None) -> None:
        self.artifacts_root = artifacts_root

    def resolve_plan(
        self, plan_id: str, artifacts_root: Path | None = None
    ) -> tuple[InventoryRunManifest, InventoryRunPaths]:
        """Resolve and validate an inventory run or catalog plan projection."""
        root = artifacts_root or self.artifacts_root or resolve_paths().artifacts_root
        existing_paths = inventory_run_paths(root, plan_id)
        if existing_paths.run_manifest_path().is_file():
            manifest = read_run_manifest(existing_paths)
            if manifest is not None:
                return manifest, existing_paths

        resources = derive_resources()
        chunk_size = _effective_chunk_size(None)
        projection = project_catalog_plan(
            plan_id,
            artifacts_root=root,
            profile=resources,
            chunk_size=chunk_size,
        )
        run_paths = inventory_run_paths(root, projection.run_id)
        existing = read_run_manifest(run_paths)
        if existing is not None:
            return existing, run_paths
        identity = _run_identity(projection, chunk_size)
        manifest = write_run_manifest(
            run_paths,
            work_order_path=projection.paths.work_order_path(),
            **_manifest_kwargs(identity),
        )
        return manifest, run_paths

    def get_chunk_count(
        self, plan: tuple[InventoryRunManifest, InventoryRunPaths]
    ) -> int:
        """Return total chunk count of the work order."""
        manifest = plan[0]
        if manifest.work_order_rows == 0:
            return 0
        return -(-manifest.work_order_rows // manifest.chunk_size)

    def default_destination(self, plan_id: str) -> Path:
        """Derive pipeline-namespaced export destination."""
        return distribution_root() / self.pipeline_name / plan_id[:8]

    def export_worker_bundle(
        self,
        plan: tuple[InventoryRunManifest, InventoryRunPaths],
        assignment: WorkerAssignment,
        bundle_dir: Path,
    ) -> None:
        """Copy run manifest and work order Parquet file into worker bundle."""
        manifest, run_paths = plan
        bundle_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run_paths.run_manifest_path(), bundle_dir / "run_manifest.json")
        shutil.copy2(run_paths.work_order_path(), bundle_dir / "work_order.parquet")

    def execute_worker(
        self,
        bundle_dir: Path,
        worker_id: str | None,
        *,
        workers: int | None = None,
    ) -> WorkerReceipt:
        """Run assigned work order chunks and return cryptographic receipt."""
        manifest_data = read_bundle_manifest(bundle_dir)
        plan_id = str(manifest_data["plan_id"])
        chunk_ids = [int(cid) for cid in manifest_data["chunk_ids"]]
        effective_worker = worker_id or str(manifest_data.get("worker_id", "worker"))

        manifest_file = bundle_dir / "run_manifest.json"
        raw_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        run_manifest = InventoryRunManifest.from_dict(raw_manifest)
        bundle_paths = InventoryRunPaths(
            artifacts_root=bundle_dir, run_id=run_manifest.run_id
        )
        work_order_path = bundle_dir / "work_order.parquet"

        assigned_set = set(chunk_ids)
        assigned_chunks = [
            (ident, members)
            for ident, members in iter_work_order_chunks(
                work_order_path,
                chunk_size=run_manifest.chunk_size,
                work_order_version=run_manifest.work_order_version,
            )
            if ident.ordinal in assigned_set
        ]

        profile = derive_resources()
        effective_workers = (
            workers if workers is not None and workers > 0 else profile.workers
        )
        with _cooperative_stop() as stop_requested:
            _run_pending(
                assigned_chunks,
                bundle_paths,
                run_manifest,
                run_id=run_manifest.run_id,
                http_client=None,
                workers=effective_workers,
                force_refresh=run_manifest.fetch_mode == "force_refresh",
                retry_failures=False,
                profile=profile,
                stop_requested=stop_requested,
            )

        chunk_files: list[Path] = []
        completed_ordinals: list[int] = []
        total_rows = 0
        for ident, members in assigned_chunks:
            chunk_dir = bundle_paths.chunk_dir(ident.chunk_id)
            if chunk_dir.is_dir():
                found = sorted(p for p in chunk_dir.rglob("*") if p.is_file())
                chunk_files.extend(found)
                completed_ordinals.append(ident.ordinal)
                total_rows += ident.membership_count

        return build_worker_receipt(
            pipeline=self.pipeline_name,
            plan_id=plan_id,
            worker_id=effective_worker,
            completed_chunks=completed_ordinals,
            row_count=total_rows,
            chunk_files=chunk_files,
            bundle_dir=bundle_dir,
        )

    def adopt_worker_bundle(
        self,
        plan: tuple[InventoryRunManifest, InventoryRunPaths],
        bundle_dir: Path,
        receipt: WorkerReceipt,
    ) -> ImportReport:
        """Verify returned chunk files and copy them into run tree."""
        manifest, coordinator_paths = plan
        adopted: list[int] = []
        ignored: list[int] = []

        for rel_path, expected_digest in receipt.digests.items():
            incoming = bundle_dir / rel_path
            if not incoming.is_file():
                raise ValueError(f"receipt references missing file: {incoming}")
            if file_sha256(incoming) != expected_digest:
                raise ValueError(f"digest mismatch for incoming file: {incoming}")

        bundle_paths = InventoryRunPaths(
            artifacts_root=bundle_dir, run_id=manifest.run_id
        )
        work_order_path = coordinator_paths.work_order_path()
        chunks_by_ordinal = {
            ident.ordinal: ident
            for ident, _ in iter_work_order_chunks(
                work_order_path,
                chunk_size=manifest.chunk_size,
                work_order_version=manifest.work_order_version,
            )
        }

        for ordinal in receipt.completed_chunks:
            ident = chunks_by_ordinal.get(ordinal)
            if ident is None:
                raise ValueError(f"unknown chunk ordinal {ordinal}")
            src_chunk = bundle_paths.chunk_dir(ident.chunk_id)
            dst_chunk = coordinator_paths.chunk_dir(ident.chunk_id)
            if dst_chunk.is_dir():
                ignored.append(ordinal)
                continue
            if src_chunk.is_dir():
                shutil.copytree(src_chunk, dst_chunk)
                validation = validate_committed_chunk(
                    coordinator_paths, ident.chunk_id, manifest, ident
                )
                if not validation.valid:
                    shutil.rmtree(dst_chunk, ignore_errors=True)
                    raise ValueError(
                        f"chunk {ordinal} failed validation: {validation.status}"
                    )
                adopted.append(ordinal)

        return ImportReport(
            pipeline=self.pipeline_name,
            plan_id=manifest.run_id,
            worker_id=receipt.worker_id,
            adopted_chunks=tuple(adopted),
            ignored_chunks=tuple(ignored),
        )
