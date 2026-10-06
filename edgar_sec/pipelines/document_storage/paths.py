"""Directory layout and artifact naming for the document storage pipeline.

Run checkpoints are transient execution state; snapshots and review runs are
published outputs, and the two never share a directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    CHECKPOINTS_DIR,
    DOCUMENTS_DATASET,
    FIXTURE_MANIFEST_NAME,
    FIXTURES_DIR,
    PAYLOAD_DB_NAME,
    REVIEW_RUNS_DIR,
    RUNS_DIR,
    SNAPSHOTS_DIR,
    TRANSIENT_DIR,
    ProjectPaths,
    current_pointer_path,
)

SNAPSHOT_ARTIFACT_NAME = "documents.parquet"
RUN_MANIFEST_NAME = "manifest.json"
CASES_DIR = "cases"
REVIEW_MANIFEST_NAME = "review_manifest.jsonl"
EXHIBITS_DATASET = "document_exhibits"
EXHIBIT_SNAPSHOT_NAME = "exhibits.parquet"
CHUNKS_DIR_NAME = "chunks"

#: Stamped into this pipeline's manifests and pointer. Owned here because which
#: phase produced a snapshot is a fact about the pipeline, not the shared writer.
DOCUMENTS_PHASE = "025_webpage_storage"


def chunk_checkpoint_path(chunks_dir: Path | str, chunk_id: str) -> Path:
    return Path(chunks_dir) / f"chunk-{chunk_id}.parquet"


def catalog_delegation_path(checkpoint: Path | str) -> Path:
    """Sidecar path for a checkpoint's delegated-exhibit targets."""
    return Path(checkpoint).with_suffix(".delegations.json")


@dataclass(frozen=True, slots=True)
class DocumentStoragePaths:
    """Path layout for the document storage pipeline and its datasets."""

    artifacts_root: Path

    @classmethod
    def from_project(cls, project_paths: ProjectPaths) -> DocumentStoragePaths:
        return cls(artifacts_root=project_paths.artifacts_root)

    @property
    def documents_root(self) -> Path:
        return self.artifacts_root / DOCUMENTS_DATASET / SNAPSHOTS_DIR

    @property
    def snapshots_root(self) -> Path:
        """Alias for documents_root."""
        return self.documents_root

    @property
    def document_transient_root(self) -> Path:
        return self.artifacts_root / TRANSIENT_DIR / DOCUMENTS_DATASET

    @property
    def fixtures_root(self) -> Path:
        return self.artifacts_root / FIXTURES_DIR

    @property
    def review_runs_root(self) -> Path:
        return self.artifacts_root / DOCUMENTS_DATASET / REVIEW_RUNS_DIR

    @property
    def exhibits_root(self) -> Path:
        return self.artifacts_root / EXHIBITS_DATASET / SNAPSHOTS_DIR

    def snapshot_dir(self, snapshot_id: str) -> Path:
        return self.snapshots_root / snapshot_id

    def snapshot_artifact(self, snapshot_id: str) -> Path:
        return self.snapshot_dir(snapshot_id) / SNAPSHOT_ARTIFACT_NAME

    def current_pointer_path(self) -> Path:
        return current_pointer_path(self.snapshots_root)

    def run_dir(self, run_id: str) -> Path:
        return self.document_transient_root / RUNS_DIR / run_id

    def run_checkpoints_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / CHECKPOINTS_DIR

    def run_chunks_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / CHUNKS_DIR_NAME

    def chunk_checkpoint(self, run_id: str, chunk_id: str) -> Path:
        return chunk_checkpoint_path(self.run_chunks_dir(run_id), chunk_id)

    def fixture_dir(self, fixture_id: str) -> Path:
        return self.fixtures_root / fixture_id

    def fixture_db_path(self, fixture_id: str) -> Path:
        return self.fixture_dir(fixture_id) / PAYLOAD_DB_NAME

    def fixture_manifest_path(self, fixture_id: str) -> Path:
        return self.fixture_dir(fixture_id) / FIXTURE_MANIFEST_NAME

    def review_run_dir(self, run_id: str) -> Path:
        return self.review_runs_root / run_id


__all__ = [
    "CASES_DIR",
    "CHUNKS_DIR_NAME",
    "DOCUMENTS_PHASE",
    "EXHIBITS_DATASET",
    "EXHIBIT_SNAPSHOT_NAME",
    "REVIEW_MANIFEST_NAME",
    "RUN_MANIFEST_NAME",
    "SNAPSHOT_ARTIFACT_NAME",
    "DocumentStoragePaths",
    "catalog_delegation_path",
    "chunk_checkpoint_path",
]
