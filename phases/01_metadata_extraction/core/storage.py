"""Composition root for phase 1 checkpoint and output storage."""

from __future__ import annotations

from collections.abc import Iterable

from defs.storage import (
    ArtifactRef,
    ChunkRange,
    DatasetSpec,
    RunContext,
    make_chunk_backend,
)

from .schemas import DATASET_NAME, SCHEMA_VERSION, SUBMISSION_METADATA_SCHEMA


class Phase1CheckpointStore:
    """Phase-owned validation boundary over immutable storage artifacts."""

    def __init__(self, backend, *, spec: DatasetSpec, run: RunContext):
        self.backend = backend
        self.spec = spec
        self.run = run
        self.backend.init(spec=spec, run=run)

    def write(self, rows: Iterable[dict], chunk: ChunkRange) -> ArtifactRef:
        return self.backend.write_chunk(chunk, rows)

    def list(self) -> list[ArtifactRef]:
        return self.backend.list_chunks()

    def find(
        self, chunk_id: int, chunk: ChunkRange | None = None
    ) -> ArtifactRef | None:
        for ref in self.list():
            if ref.chunk_id != chunk_id:
                continue
            if chunk is not None and (
                ref.start_row != chunk.start_row or ref.end_row != chunk.end_row
            ):
                continue
            return ref
        return None

    def load(self, chunk_id: int) -> list[dict]:
        return self.backend.load_chunk_records(chunk_id)

    def finalize(self, rows: Iterable[dict], output_path: str) -> ArtifactRef:
        return self.backend.finalize_records(rows, output_path)

    def finalize_chunks(self, output_path: str) -> ArtifactRef:
        """Materialize completed chunks through the backend's native path."""
        return self.backend.finalize(output_path)


def make_checkpoint_store(
    options, *, input_fingerprint: str = "", root: str | None = None
) -> Phase1CheckpointStore:
    options.validate()
    return make_phase_store(
        options.storage_format,
        root or options.artifacts_dir,
        options.run_id,
        input_fingerprint,
    )


def make_phase_store(
    storage_format: str, root: str, run_id: str = "local", input_fingerprint: str = ""
) -> Phase1CheckpointStore:
    spec = DatasetSpec(
        name=DATASET_NAME,
        schema_version=SCHEMA_VERSION,
        key_field="cik",
        arrow_schema=SUBMISSION_METADATA_SCHEMA,
    )
    backend = make_chunk_backend(storage_format, root)
    return Phase1CheckpointStore(
        backend,
        spec=spec,
        run=RunContext(run_id=run_id, input_fingerprint=input_fingerprint),
    )


__all__ = ["Phase1CheckpointStore", "make_checkpoint_store", "make_phase_store"]
