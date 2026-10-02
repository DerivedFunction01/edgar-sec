"""Directory layout and artifact naming conventions for the document storage pipeline.

All paths derive from the shared artifacts root so the pipeline never embeds
hardcoded artifact paths. Resumable run checkpoints are cleanly separated from
published snapshots: chunks are intermediate execution state, while snapshots
and review deliverables are published outputs.
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
CASES_DIR = "cases"
REVIEW_MANIFEST_NAME = "review_manifest.jsonl"
EXHIBITS_DATASET = "document_exhibits"
EXHIBIT_SNAPSHOT_NAME = "exhibits.parquet"
CHUNKS_DIR_NAME = "chunks"


def chunk_checkpoint_path(chunks_dir: Path | str, chunk_id: str) -> Path:
    """Return the Parquet checkpoint path for one chunk."""
    return Path(chunks_dir) / f"chunk-{chunk_id}.parquet"


@dataclass(frozen=True, slots=True)
class DocumentStoragePaths:
    """Path layout for the document storage pipeline and its datasets."""

    artifacts_root: Path

    @classmethod
    def from_project(cls, project_paths: ProjectPaths) -> DocumentStoragePaths:
        return cls(artifacts_root=project_paths.artifacts_root)

    @property
    def documents_root(self) -> Path:
        """Published document snapshots root directory."""
        return self.artifacts_root / DOCUMENTS_DATASET / SNAPSHOTS_DIR

    @property
    def snapshots_root(self) -> Path:
        """Alias for documents_root."""
        return self.documents_root

    @property
    def document_transient_root(self) -> Path:
        """Run-scoped staging root for the document storage pipeline."""
        return self.artifacts_root / TRANSIENT_DIR / DOCUMENTS_DATASET

    @property
    def fixtures_root(self) -> Path:
        """Committed raw-payload fixtures root directory."""
        return self.artifacts_root / FIXTURES_DIR

    @property
    def review_runs_root(self) -> Path:
        """Durable root of generated review runs."""
        return self.artifacts_root / DOCUMENTS_DATASET / REVIEW_RUNS_DIR

    @property
    def exhibits_root(self) -> Path:
        """Published document exhibits snapshots root directory."""
        return self.artifacts_root / EXHIBITS_DATASET / SNAPSHOTS_DIR

    def snapshot_dir(self, snapshot_id: str) -> Path:
        """Return the directory for one published document snapshot."""
        return self.snapshots_root / snapshot_id

    def snapshot_artifact(self, snapshot_id: str) -> Path:
        """Return the Parquet artifact path for one published document snapshot."""
        return self.snapshot_dir(snapshot_id) / SNAPSHOT_ARTIFACT_NAME

    def current_pointer_path(self) -> Path:
        """Return the pointer file naming the currently published snapshot."""
        return current_pointer_path(self.snapshots_root)

    def run_dir(self, run_id: str) -> Path:
        """Return the staging directory for one document-storage run."""
        return self.document_transient_root / RUNS_DIR / run_id

    def run_checkpoints_dir(self, run_id: str) -> Path:
        """Return the resumable-checkpoint directory for one run."""
        return self.run_dir(run_id) / CHECKPOINTS_DIR

    def run_chunks_dir(self, run_id: str) -> Path:
        """Return the worker chunk directory for one run."""
        return self.run_dir(run_id) / CHUNKS_DIR_NAME

    def chunk_checkpoint(self, run_id: str, chunk_id: str) -> Path:
        """Return the checkpoint path for a specific chunk in a run."""
        return chunk_checkpoint_path(self.run_chunks_dir(run_id), chunk_id)

    def fixture_dir(self, fixture_id: str) -> Path:
        """Return the directory for one raw-payload fixture."""
        return self.fixtures_root / fixture_id

    def fixture_db_path(self, fixture_id: str) -> Path:
        """Return the SQLite path holding one fixture's raw payloads."""
        return self.fixture_dir(fixture_id) / PAYLOAD_DB_NAME

    def fixture_manifest_path(self, fixture_id: str) -> Path:
        """Return the lineage manifest for one fixture."""
        return self.fixture_dir(fixture_id) / FIXTURE_MANIFEST_NAME

    def review_run_dir(self, run_id: str) -> Path:
        """Return the directory one review run's artifacts are written into."""
        return self.review_runs_root / run_id


__all__ = [
    "CASES_DIR",
    "CHUNKS_DIR_NAME",
    "EXHIBITS_DATASET",
    "EXHIBIT_SNAPSHOT_NAME",
    "REVIEW_MANIFEST_NAME",
    "SNAPSHOT_ARTIFACT_NAME",
    "DocumentStoragePaths",
    "chunk_checkpoint_path",
]
