"""Distribution adapter for the document inventory pipeline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.runtime.paths import distribution_root, resolve_paths
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.distribution.guards import (
    assert_work_digest,
    read_bundle_manifest,
)
from edgar_sec.infra.distribution.protocol import (
    DistributionWork,
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
    _run_pending,
)
from edgar_sec.pipelines.document_inventory.paths import (
    CHUNKS_DIR,
    ENTRIES_FILE,
    InventoryRunPaths,
    MANIFEST_FILE,
    OUTCOMES_FILE,
    RUN_MANIFEST_FILE,
    WORK_ORDER_FILE,
    inventory_run_paths,
)
from edgar_sec.pipelines.document_inventory.run_manifest import (
    InventoryRunManifest,
    iter_work_order_chunks,
    read_run_manifest,
    validate_work_order,
)
from edgar_sec.pipelines.document_inventory.run_state import (
    discover_run_statuses,
    load_run_status,
)


class InventoryDistributionAdapter:
    pipeline_name = "inventory"

    def __init__(
        self, artifacts_root: Path | None = None, *, http_client: Any | None = None
    ) -> None:
        self.artifacts_root = artifacts_root
        self.http_client = http_client

    def _root(self, artifacts_root: Path | None = None) -> Path:
        return (
            artifacts_root or self.artifacts_root or resolve_paths().artifacts_root
        ).resolve()

    def list_work_items(
        self, artifacts_root: Path | None = None
    ) -> tuple[DistributionWork, ...]:
        root = self._root(artifacts_root)
        found = []
        for status in discover_run_statuses(root):
            if (
                not status.valid
                or status.locked
                or status.state in {"cancelled", "published"}
            ):
                continue
            try:
                work = self.resolve_work(status.run_id, root)
                found.append(self.describe_work(status.run_id, work))
            except (OSError, ValueError):
                continue
        return tuple(found)

    def resolve_work(
        self, work_id: str, artifacts_root: Path | None = None
    ) -> tuple[InventoryRunManifest, InventoryRunPaths]:
        root = self._root(artifacts_root)
        status = load_run_status(root, work_id)
        if not status.valid:
            raise ValueError(f"inventory run is invalid: {work_id}")
        if status.locked:
            raise ValueError(f"inventory run is locked: {work_id}")
        if status.state == "published":
            raise ValueError(f"published inventory run is not distributable: {work_id}")
        if status.state == "cancelled":
            raise ValueError(f"cancelled inventory run is not distributable: {work_id}")
        paths = inventory_run_paths(root, work_id)
        manifest = read_run_manifest(paths)
        if manifest is None:
            raise ValueError(f"inventory run manifest is missing: {work_id}")
        return manifest, paths

    def describe_work(
        self,
        work_id: str,
        work: tuple[InventoryRunManifest, InventoryRunPaths],
    ) -> DistributionWork:
        manifest, paths = work
        if manifest.run_id != work_id or paths.run_id != work_id:
            raise ValueError("inventory run identity differs from requested work")
        digest = sha256_text(
            f"{canonical_json(manifest.to_dict())}:{manifest.work_order_digest}"
        )
        chunk_count = (
            -(-manifest.work_order_rows // manifest.chunk_size)
            if manifest.work_order_rows
            else 0
        )
        return DistributionWork(
            work_id=work_id,
            label=f"Inventory run {work_id}",
            work_digest=digest,
            chunk_count=chunk_count,
        )

    def default_destination(self, work_id: str) -> Path:
        return distribution_root() / self.pipeline_name / work_id[:8]

    def export_worker_bundle(
        self,
        work: tuple[InventoryRunManifest, InventoryRunPaths],
        assignment: WorkerAssignment,
        bundle_dir: Path,
    ) -> None:
        manifest, paths = work
        bundle_paths = InventoryRunPaths(
            artifacts_root=bundle_dir, run_id=manifest.run_id
        )
        shutil.rmtree(bundle_paths.run_root / CHUNKS_DIR, ignore_errors=True)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths.run_manifest_path(), bundle_dir / RUN_MANIFEST_FILE)
        shutil.copy2(paths.work_order_path(), bundle_dir / WORK_ORDER_FILE)

    def execute_worker(
        self,
        bundle_dir: Path,
        worker_id: str | None,
        *,
        workers: int | None = None,
    ) -> WorkerReceipt:
        assignment = read_bundle_manifest(bundle_dir)
        work_id = str(assignment["work_id"])
        assigned_indexes = tuple(int(value) for value in assignment["chunk_ids"])
        effective_worker = worker_id or str(assignment["worker_id"])
        manifest_file = bundle_dir / RUN_MANIFEST_FILE
        raw_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        run_manifest = InventoryRunManifest.from_dict(raw_manifest)
        if run_manifest.run_id != work_id:
            raise ValueError("inventory run manifest differs from bundle work identity")
        bundle_paths = InventoryRunPaths(artifacts_root=bundle_dir, run_id=work_id)
        work_digest = self.describe_work(
            work_id, (run_manifest, bundle_paths)
        ).work_digest
        assert_work_digest(assignment["work_digest"], work_digest)
        work_order_path = bundle_dir / WORK_ORDER_FILE
        work_order_identity = validate_work_order(work_order_path)
        if (
            work_order_identity.digest != run_manifest.work_order_digest
            or work_order_identity.row_count != run_manifest.work_order_rows
        ):
            raise ValueError(
                "bundled inventory work order differs from its run manifest"
            )
        assigned_set = set(assigned_indexes)
        assigned_chunks = [
            (identity, members)
            for identity, members in iter_work_order_chunks(
                work_order_path,
                chunk_size=run_manifest.chunk_size,
                work_order_version=run_manifest.work_order_version,
            )
            if identity.ordinal in assigned_set
        ]
        if {identity.ordinal for identity, _ in assigned_chunks} != assigned_set:
            raise ValueError("assignment contains an unknown inventory chunk")

        profile = derive_resources()
        effective_workers = (
            workers if workers is not None and workers > 0 else profile.workers
        )
        with _cooperative_stop() as stop_requested:
            _run_pending(
                assigned_chunks,
                bundle_paths,
                run_manifest,
                run_id=work_id,
                http_client=self.http_client,
                workers=effective_workers,
                force_refresh=run_manifest.fetch_mode == "force_refresh",
                retry_failures=False,
                profile=profile,
                stop_requested=stop_requested,
            )

        output_files: list[Path] = []
        completed: list[int] = []
        outcome_count = 0
        for identity, _ in assigned_chunks:
            validation = validate_committed_chunk(
                bundle_paths,
                identity.chunk_id,
                run=run_manifest,
                chunk=identity,
            )
            if not validation.valid or validation.attempt_id is None:
                continue
            attempt_dir = bundle_paths.attempt_dir(
                identity.chunk_id, validation.attempt_id
            )
            required_files = {
                attempt_dir / MANIFEST_FILE,
                attempt_dir / OUTCOMES_FILE,
                attempt_dir / ENTRIES_FILE,
            }
            actual_files = {path for path in attempt_dir.rglob("*") if path.is_file()}
            if actual_files != required_files:
                raise ValueError(
                    f"inventory chunk {identity.ordinal} has unexpected output files"
                )
            output_files.append(bundle_paths.chunk_pointer_path(identity.chunk_id))
            output_files.extend(sorted(required_files))
            completed.append(identity.ordinal)
            outcome_count += identity.membership_count

        return build_worker_receipt(
            pipeline=self.pipeline_name,
            work_id=work_id,
            work_digest=work_digest,
            assignment_id=str(assignment.get("assignment_id", "")),
            worker_id=effective_worker,
            completed_chunks=completed,
            output_files=output_files,
            bundle_root=bundle_dir,
            result_metadata={"outcome_rows": outcome_count},
        )

    def adopt_worker_bundle(
        self,
        work: tuple[InventoryRunManifest, InventoryRunPaths],
        bundle_dir: Path,
        receipt: WorkerReceipt,
    ) -> ImportReport:
        manifest, coordinator_paths = work
        if receipt.work_id != manifest.run_id:
            raise ValueError("receipt does not belong to the resolved inventory run")
        expected_digest = self.describe_work(manifest.run_id, work).work_digest
        assert_work_digest(expected_digest, receipt.work_digest)
        bundle_manifest = read_bundle_manifest(bundle_dir)
        assigned = set(int(value) for value in bundle_manifest["chunk_ids"])
        completed = set(receipt.completed_chunks)
        if not completed.issubset(assigned):
            raise ValueError("receipt contains chunks outside its inventory assignment")

        source_paths = InventoryRunPaths(
            artifacts_root=bundle_dir, run_id=manifest.run_id
        )
        chunks_by_ordinal = {
            identity.ordinal: identity
            for identity, _ in iter_work_order_chunks(
                coordinator_paths.work_order_path(),
                chunk_size=manifest.chunk_size,
                work_order_version=manifest.work_order_version,
            )
        }
        for ordinal, identity in chunks_by_ordinal.items():
            if source_paths.chunk_pointer_path(identity.chunk_id).is_file() and (
                ordinal not in assigned or ordinal not in completed
            ):
                raise ValueError(
                    "worker bundle contains an unreceipted committed chunk"
                )
        expected_files: set[str] = set()
        attempts: dict[int, tuple[str, Path]] = {}
        for ordinal in sorted(completed):
            identity = chunks_by_ordinal.get(ordinal)
            if identity is None:
                raise ValueError(f"unknown inventory chunk ordinal {ordinal}")
            validation = validate_committed_chunk(
                source_paths,
                identity.chunk_id,
                run=manifest,
                chunk=identity,
            )
            if not validation.valid or validation.attempt_id is None:
                raise ValueError(f"worker chunk {ordinal} failed validation")
            attempt_dir = source_paths.attempt_dir(
                identity.chunk_id, validation.attempt_id
            )
            files = {path for path in attempt_dir.rglob("*") if path.is_file()}
            required_files = {
                attempt_dir / MANIFEST_FILE,
                attempt_dir / OUTCOMES_FILE,
                attempt_dir / ENTRIES_FILE,
            }
            if files != required_files:
                raise ValueError(
                    f"inventory chunk {ordinal} has unexpected output files"
                )
            expected_files.update(
                path.relative_to(bundle_dir).as_posix() for path in files
            )
            pointer = source_paths.chunk_pointer_path(identity.chunk_id)
            if not pointer.is_file():
                raise ValueError(f"inventory chunk {ordinal} has no commit pointer")
            expected_files.add(pointer.relative_to(bundle_dir).as_posix())
            attempts[ordinal] = (identity.chunk_id, attempt_dir)
        if expected_files != set(receipt.file_records):
            raise ValueError(
                "inventory receipt files differ from completed chunk attempts"
            )

        adopted: list[int] = []
        ignored: list[int] = []
        pending: list[tuple[int, str, Path]] = []
        for ordinal, (chunk_id, source_dir) in attempts.items():
            target_dir = coordinator_paths.chunk_dir(chunk_id)
            if target_dir.is_dir():
                existing = validate_committed_chunk(
                    coordinator_paths,
                    chunk_id,
                    run=manifest,
                    chunk=chunks_by_ordinal[ordinal],
                )
                incoming = validate_committed_chunk(
                    source_paths,
                    chunk_id,
                    run=manifest,
                    chunk=chunks_by_ordinal[ordinal],
                )
                if (
                    existing.valid
                    and incoming.valid
                    and existing.attempt_id == incoming.attempt_id
                ):
                    ignored.append(ordinal)
                    continue
                raise ValueError(
                    f"inventory chunk {ordinal} already exists with different content"
                )
            if target_dir.exists():
                raise ValueError(f"inventory chunk {ordinal} has a conflicting path")
            pending.append((ordinal, chunk_id, source_dir))

        for ordinal, chunk_id, source_dir in pending:
            target_dir = coordinator_paths.chunk_dir(chunk_id)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            staging_dir = target_dir.with_name(f".{target_dir.name}.{uuid4().hex}.tmp")
            staging_dir.mkdir()
            try:
                shutil.copy2(
                    source_paths.chunk_pointer_path(chunk_id),
                    staging_dir / coordinator_paths.chunk_pointer_path(chunk_id).name,
                )
                shutil.copytree(source_dir, staging_dir / source_dir.name)
                staging_dir.rename(target_dir)
            except FileExistsError as exc:
                raise ValueError(
                    f"inventory chunk {ordinal} appeared during worker import"
                ) from exc
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)
            validation = validate_committed_chunk(
                coordinator_paths,
                chunk_id,
                run=manifest,
                chunk=chunks_by_ordinal[ordinal],
            )
            if not validation.valid:
                shutil.rmtree(target_dir, ignore_errors=True)
                raise ValueError(
                    f"inventory chunk {ordinal} failed coordinator validation"
                )
            adopted.append(ordinal)

        return ImportReport(
            pipeline=self.pipeline_name,
            work_id=manifest.run_id,
            worker_id=receipt.worker_id,
            adopted_chunks=tuple(sorted(adopted)),
            ignored_chunks=tuple(sorted(ignored)),
        )
