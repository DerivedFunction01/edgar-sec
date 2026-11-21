"""Pipeline-neutral work distribution contracts and transfer data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DistributionWork:
    work_id: str
    label: str
    work_digest: str
    chunk_count: int


@dataclass(frozen=True, slots=True)
class WorkerAssignment:
    pipeline: str
    work_id: str
    work_digest: str
    worker_id: str
    chunk_ids: tuple[int, ...]
    assignment_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkerFile:
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class WorkerReceipt:
    pipeline: str
    work_id: str
    work_digest: str
    assignment_id: str
    worker_id: str
    completed_chunks: tuple[int, ...]
    file_records: dict[str, WorkerFile]
    result_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportReport:
    pipeline: str
    work_id: str
    worker_id: str
    adopted_chunks: tuple[int, ...]
    ignored_chunks: tuple[int, ...]


class DistributionAdapter(Protocol):
    @property
    def pipeline_name(self) -> str: ...

    def list_work_items(
        self, artifacts_root: Path | None = None
    ) -> tuple[DistributionWork, ...]: ...

    def resolve_work(self, work_id: str, artifacts_root: Path | None = None) -> Any: ...

    def describe_work(self, work_id: str, work: Any) -> DistributionWork: ...

    def default_destination(self, work_id: str) -> Path: ...

    def export_worker_bundle(
        self,
        work: Any,
        assignment: WorkerAssignment,
        bundle_dir: Path,
    ) -> None: ...

    def execute_worker(
        self,
        bundle_dir: Path,
        worker_id: str | None,
        *,
        workers: int | None = None,
    ) -> WorkerReceipt: ...

    def adopt_worker_bundle(
        self,
        work: Any,
        bundle_dir: Path,
        receipt: WorkerReceipt,
    ) -> ImportReport: ...
