"""Distribution adapter bridging metadata sync to infra.distribution."""

from __future__ import annotations

import shutil
import os
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.runtime.paths import distribution_root
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

from .checkpoints import inspect_chunk
from .commands.client import build_client
from .discovery import list_plans
from .distribution import copy_bundle
from .options import BundleRunPaths
from .paths import MetadataPaths, resolve_metadata_paths, resolve_run_paths
from .planner import Plan, load_plan
from .worker import resolve_workers, run_chunk_ids


@dataclass(frozen=True, slots=True)
class _ResolvedMetadataWork:
    plan: Plan
    metadata: MetadataPaths


class MetadataDistributionAdapter:
    pipeline_name = "metadata"

    def __init__(
        self,
        artifacts_root: Path | None = None,
        *,
        client_factory: Callable[[], Any] = build_client,
    ) -> None:
        self.artifacts_root = artifacts_root
        self.client_factory = client_factory

    def list_work_items(
        self, artifacts_root: Path | None = None
    ) -> tuple[DistributionWork, ...]:
        metadata = resolve_metadata_paths(artifacts_root or self.artifacts_root)
        found: list[DistributionWork] = []
        for candidate in list_plans(metadata):
            work_id = str(candidate["plan_id"])
            if not candidate["readable"]:
                continue
            try:
                plan = load_plan(resolve_run_paths(work_id, metadata.artifacts_root))
            except (OSError, ValueError):
                continue
            found.append(self.describe_work(work_id, plan))
        return tuple(found)

    def resolve_work(
        self, work_id: str, artifacts_root: Path | None = None
    ) -> _ResolvedMetadataWork:
        metadata = resolve_metadata_paths(artifacts_root or self.artifacts_root)
        plan = load_plan(resolve_run_paths(work_id, metadata.artifacts_root))
        return _ResolvedMetadataWork(plan, metadata)

    def describe_work(self, work_id: str, work: Any) -> DistributionWork:
        plan = work.plan if isinstance(work, _ResolvedMetadataWork) else work
        if plan.plan_id != work_id:
            raise ValueError("metadata plan identity differs from requested work")
        digest = sha256_text(canonical_json(plan.to_manifest()))
        return DistributionWork(
            work_id=work_id,
            label=f"Metadata {plan.kind} plan {work_id}",
            work_digest=digest,
            chunk_count=plan.chunk_count,
        )

    def default_destination(self, work_id: str) -> Path:
        return distribution_root() / self.pipeline_name / work_id[:8]

    def export_worker_bundle(
        self,
        work: _ResolvedMetadataWork,
        assignment: WorkerAssignment,
        bundle_dir: Path,
    ) -> None:
        bundle_paths = BundleRunPaths(bundle_root=bundle_dir, plan_id=work.plan.plan_id)
        shutil.rmtree(bundle_paths.chunk_dir, ignore_errors=True)
        source_paths = resolve_run_paths(
            work.plan.plan_id, work.metadata.artifacts_root
        )
        copy_bundle(source_paths, bundle_dir)

    def execute_worker(
        self,
        bundle_dir: Path,
        worker_id: str | None,
        *,
        workers: int | None = None,
    ) -> WorkerReceipt:
        manifest = read_bundle_manifest(bundle_dir)
        work_id = str(manifest["work_id"])
        chunk_ids = [int(chunk_id) for chunk_id in manifest["chunk_ids"]]
        effective_worker = worker_id or str(manifest["worker_id"])
        bundle_paths = BundleRunPaths(bundle_root=bundle_dir, plan_id=work_id)
        plan = load_plan(bundle_paths)
        work_digest = self.describe_work(work_id, plan).work_digest
        assert_work_digest(manifest["work_digest"], work_digest)
        results = run_chunk_ids(
            self.client_factory(),
            plan,
            bundle_paths,
            chunk_ids,
            snapshot_id=None,
            workers=resolve_workers(workers),
        )
        chunk_files = [Path(result.path) for result in results]
        completed = [result.chunk_id for result in results]
        row_count = sum(result.row_count for result in results)
        return build_worker_receipt(
            pipeline=self.pipeline_name,
            work_id=work_id,
            work_digest=work_digest,
            assignment_id=str(manifest.get("assignment_id", "")),
            worker_id=effective_worker,
            completed_chunks=completed,
            output_files=chunk_files,
            bundle_root=bundle_dir,
            result_metadata={"row_count": row_count},
        )

    def adopt_worker_bundle(
        self,
        work: _ResolvedMetadataWork,
        bundle_dir: Path,
        receipt: WorkerReceipt,
    ) -> ImportReport:
        plan = work.plan
        if receipt.work_id != plan.plan_id:
            raise ValueError("receipt does not belong to the resolved metadata plan")
        assert_work_digest(
            self.describe_work(plan.plan_id, plan).work_digest, receipt.work_digest
        )
        coordinator_paths = resolve_run_paths(
            plan.plan_id, work.metadata.artifacts_root
        )
        files_by_chunk: dict[int, tuple[Path, str]] = {}
        for relative_path, record in receipt.file_records.items():
            incoming = bundle_dir / relative_path
            stem = incoming.stem
            if not stem.startswith("chunk_"):
                raise ValueError(f"unexpected metadata output file: {relative_path}")
            try:
                chunk_id = int(stem.removeprefix("chunk_"))
            except ValueError as exc:
                raise ValueError(
                    f"invalid metadata chunk file: {relative_path}"
                ) from exc
            if chunk_id in files_by_chunk or chunk_id not in receipt.completed_chunks:
                raise ValueError(
                    f"metadata output is not in completed chunks: {relative_path}"
                )
            files_by_chunk[chunk_id] = (incoming, record.sha256)
        if set(files_by_chunk) != set(receipt.completed_chunks):
            raise ValueError("metadata receipt is missing a completed chunk file")
        output_root = bundle_dir / "chunks"
        actual_files = {
            path.relative_to(bundle_dir).as_posix()
            for path in output_root.rglob("*")
            if path.is_file()
        }
        if actual_files != set(receipt.file_records):
            raise ValueError(
                "metadata bundle has unreceipted or unexpected output files"
            )

        adopted: list[int] = []
        ignored: list[int] = []
        pending: list[tuple[int, Path, Path]] = []
        for chunk_id, (incoming, expected_digest) in sorted(files_by_chunk.items()):
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
            pending.append((chunk_id, incoming, target))

        for chunk_id, incoming, target in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            try:
                shutil.copy2(incoming, temporary)
                os.link(temporary, target)
            except FileExistsError as exc:
                raise ValueError(
                    f"chunk {chunk_id} appeared during worker import"
                ) from exc
            finally:
                temporary.unlink(missing_ok=True)
            adopted.append(chunk_id)
        return ImportReport(
            pipeline=self.pipeline_name,
            work_id=plan.plan_id,
            worker_id=receipt.worker_id,
            adopted_chunks=tuple(sorted(adopted)),
            ignored_chunks=tuple(sorted(ignored)),
        )
