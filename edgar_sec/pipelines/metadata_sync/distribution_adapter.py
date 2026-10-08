"""Distribution adapter bridging metadata sync to infra.distribution."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import distribution_root
from edgar_sec.infra.distribution.guards import read_bundle_manifest
from edgar_sec.infra.distribution.protocol import (
    ImportReport,
    WorkerAssignment,
    WorkerReceipt,
)
from edgar_sec.infra.distribution.receipt import build_worker_receipt

from .checkpoints import inspect_chunk
from .commands.client import build_client
from .distribution import copy_bundle
from .options import BundleRunPaths
from .paths import resolve_run_paths
from .planner import Plan, load_plan
from .worker import resolve_workers, run_chunk_ids


class MetadataDistributionAdapter:
    """Distribution adapter for the metadata sync pipeline."""

    pipeline_name = "metadata"

    def __init__(self, artifacts_root: Path | None = None) -> None:
        self.artifacts_root = artifacts_root

    def resolve_plan(self, plan_id: str, artifacts_root: Path | None = None) -> Plan:
        """Resolve and load a metadata plan."""
        root = artifacts_root or self.artifacts_root
        return load_plan(resolve_run_paths(plan_id, root))

    def get_chunk_count(self, plan: Plan) -> int:
        """Return total chunk count of a metadata plan."""
        return plan.chunk_count

    def default_destination(self, plan_id: str) -> Path:
        """Derive pipeline-namespaced export destination."""
        return distribution_root() / self.pipeline_name / plan_id[:8]

    def export_worker_bundle(
        self,
        plan: Plan,
        assignment: WorkerAssignment,
        bundle_dir: Path,
    ) -> None:
        """Copy required plan context (plan.json, roster, diagnostics) into bundle."""
        source_paths = resolve_run_paths(plan.plan_id, self.artifacts_root)
        copy_bundle(source_paths, bundle_dir)

    def execute_worker(
        self,
        bundle_dir: Path,
        worker_id: str | None,
        *,
        workers: int | None = None,
    ) -> WorkerReceipt:
        """Run assigned chunks from bundle and return signed worker receipt."""
        manifest = read_bundle_manifest(bundle_dir)
        plan_id = str(manifest["plan_id"])
        chunk_ids = [int(cid) for cid in manifest["chunk_ids"]]
        effective_worker = worker_id or str(manifest.get("worker_id", "worker"))

        bundle_paths = BundleRunPaths(bundle_root=bundle_dir, plan_id=plan_id)
        plan = load_plan(bundle_paths)
        client = build_client()

        results = run_chunk_ids(
            client,
            plan,
            bundle_paths,
            chunk_ids,
            snapshot_id=None,
            workers=resolve_workers(workers),
        )

        chunk_files = [Path(r.path) for r in results if not r.skipped_existing]
        total_rows = sum(r.row_count for r in results)
        completed = [r.chunk_id for r in results if not r.skipped_existing]

        return build_worker_receipt(
            pipeline=self.pipeline_name,
            plan_id=plan_id,
            worker_id=effective_worker,
            completed_chunks=completed,
            row_count=total_rows,
            chunk_files=chunk_files,
            bundle_root=bundle_dir,
        )

    def adopt_worker_bundle(
        self,
        plan: Plan,
        bundle_dir: Path,
        receipt: WorkerReceipt,
    ) -> ImportReport:
        """Verify returned chunks and copy them into coordinator run tree."""
        coordinator_paths = resolve_run_paths(plan.plan_id, self.artifacts_root)
        adopted: list[int] = []
        ignored: list[int] = []

        for rel_path, expected_digest in receipt.digests.items():
            incoming = bundle_dir / rel_path
            if not incoming.is_file():
                raise ValueError(f"receipt references missing file: {incoming}")
            if file_sha256(incoming) != expected_digest:
                raise ValueError(f"digest mismatch for incoming chunk: {incoming}")

            chunk_id = int(incoming.stem.split("-")[-1])
            if (
                inspect_chunk(
                    chunk_id,
                    incoming,
                    expected_ciks=plan.chunk_ciks(chunk_id),
                    expected_fingerprint=plan.input_fingerprint or None,
                )
                is None
            ):
                raise ValueError(f"chunk {chunk_id} failed schema/row validation")

            target = coordinator_paths.chunk_file(chunk_id)
            if target.is_file():
                existing = inspect_chunk(
                    chunk_id,
                    target,
                    expected_ciks=plan.chunk_ciks(chunk_id),
                    expected_fingerprint=plan.input_fingerprint or None,
                )
                if existing is not None and existing.file_sha256 == expected_digest:
                    ignored.append(chunk_id)
                    continue
                raise ValueError(
                    f"chunk {chunk_id} already exists with different content"
                )

            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(incoming, target)
            adopted.append(chunk_id)

        return ImportReport(
            pipeline=self.pipeline_name,
            plan_id=plan.plan_id,
            worker_id=receipt.worker_id,
            adopted_chunks=tuple(sorted(adopted)),
            ignored_chunks=tuple(sorted(ignored)),
        )
