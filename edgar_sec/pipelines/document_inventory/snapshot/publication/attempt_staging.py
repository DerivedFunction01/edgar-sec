"""Validation and staging of a run's committed attempts."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.infra.storage.parquet import StagedParquetWriter
from edgar_sec.pipelines.document_inventory.checkpoint import (
    OUTCOME_SCHEMA,
    AttemptValidationError,
    validate_committed_chunk,
)
from edgar_sec.pipelines.document_inventory.paths import (
    ENTRIES_FILE,
    OUTCOMES_FILE,
    InventoryRunPaths,
)
from edgar_sec.pipelines.document_inventory.run_state.run_manifest import (
    InventoryRunManifest,
    iter_work_order_chunks,
    validate_work_order,
)
from edgar_sec.pipelines.document_inventory.snapshot.contracts.errors import (
    ValidationFailedError,
)


def _validate_input(path: Path, schema: pa.Schema, label: str) -> int:
    try:
        parquet = pq.ParquetFile(path)
    except (OSError, pa.ArrowException) as exc:
        raise ValidationFailedError(f"{label} is unreadable Parquet") from exc
    actual = parquet.schema_arrow
    if actual.names != schema.names or any(
        actual.field(name).type != field.type
        for name, field in zip(schema.names, schema, strict=True)
    ):
        raise ValidationFailedError(f"{label} schema mismatch")
    return int(parquet.metadata.num_rows)


def _copy_committed_attempts(
    run_paths: InventoryRunPaths,
    run: InventoryRunManifest,
    publication_dir: Path,
) -> tuple[Path, Path, int, int]:
    identity = validate_work_order(run_paths.work_order_path())
    if (
        identity.digest != run.work_order_digest
        or identity.row_count != run.work_order_rows
    ):
        raise ValidationFailedError("work order does not match the pinned run manifest")
    outcomes_path = publication_dir / "committed_outcomes.parquet"
    entries_path = publication_dir / "committed_entries.parquet"
    outcome_writer = StagedParquetWriter(outcomes_path, OUTCOME_SCHEMA)
    entry_writer = StagedParquetWriter(entries_path, ENTRY_SCHEMA)
    outcome_count = entry_count = chunk_count = 0
    try:
        for chunk, _members in iter_work_order_chunks(
            run_paths.work_order_path(),
            chunk_size=run.chunk_size,
            work_order_version=run.work_order_version,
        ):
            checked = validate_committed_chunk(
                run_paths, chunk.chunk_id, run=run, chunk=chunk
            )
            if not checked.valid or checked.attempt_id is None:
                raise AttemptValidationError(
                    f"committed chunk {chunk.chunk_id} is invalid: {checked.reason}"
                )
            attempt_dir = run_paths.attempt_dir(chunk.chunk_id, checked.attempt_id)
            for source, writer in (
                (attempt_dir / OUTCOMES_FILE, outcome_writer),
                (attempt_dir / ENTRIES_FILE, entry_writer),
            ):
                parquet = pq.ParquetFile(source)
                for batch in parquet.iter_batches(
                    batch_size=resolve_parquet_read_batch_size()
                ):
                    writer.write_batch(batch)
            outcome_count += checked.manifest.outcomes_rows
            entry_count += checked.manifest.entries_rows
            chunk_count += 1
            if chunk_count % 16 == 0:
                reclaim()
        outcome_writer.commit(expected_count=outcome_count)
        entry_writer.commit(expected_count=entry_count)
        final_identity = validate_work_order(run_paths.work_order_path())
        if final_identity != identity:
            raise ValidationFailedError(
                "work order changed while reading committed chunks"
            )
    except BaseException:
        outcome_writer.reset()
        entry_writer.reset()
        raise
    return outcomes_path, entries_path, outcome_count, entry_count
