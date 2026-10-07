"""Outcome/entry Parquet schemas, attempt commit, and chunk pointer for S4.

One outcome row per accession, zero-or-more entry rows per parsed page. The chunk
pointer is the commit marker: an attempt without a valid manifest and pointer is never
reused, and a crash before pointer advancement leaves the prior attempt intact.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document_inventory.models import (
    IndexParseFailure,
    InventoryEntry,
    ParsedIndexPage,
    ParserDiagnostics,
    UnrecognizedIndexPage,
)
from edgar_sec.domain.document_inventory.schemas import (
    ENTRY_SCHEMA,
    ENTRY_SCHEMA_VERSION,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect, sql_path_list
from edgar_sec.infra.storage.parquet import (
    StagedParquetWriter,
    count_parquet_rows,
    read_parquet_schema,
)

from .paths import InventoryRunPaths
from .broker import IndexFetchFailure
from .run_manifest import (
    OUTCOME_SCHEMA_VERSION,
    ChunkIdentity,
    InventoryRunManifest,
    membership_digest,
)
from .worker import IndexWorkerFailure

__all__ = [
    "ALL_STATUSES",
    "ATTEMPT_MANIFEST_VERSION",
    "AttemptManifest",
    "AttemptValidationError",
    "AttemptWriters",
    "ChunkValidation",
    "OUTCOME_SCHEMA",
    "PARSER_REFUSAL_STATUSES",
    "REFUSAL_STATUSES",
    "RETRYABLE_STATUSES",
    "advance_pointer",
    "entry_rows",
    "finalize_attempt",
    "new_attempt_id",
    "outcome_row",
    "read_attempt_manifest",
    "iter_outcome_rows",
    "split_retryable",
    "validate_committed_chunk",
]

#: Version of the attempt manifest JSON itself, independent of the Parquet schemas.
ATTEMPT_MANIFEST_VERSION = 1

OUTCOME_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("status", pa.string()),
        ("index_url", pa.string()),
        ("page_sha256", pa.string()),
        ("response_size", pa.int64()),
        ("entry_count", pa.int32()),
        ("xbrl_candidate_url", pa.string()),
        ("bundle_url", pa.string()),
        ("bundle_size", pa.int64()),
        ("diagnostics_json", pa.string()),
        ("error_code", pa.string()),
        ("error_detail", pa.string()),
    ]
)

STATUS_PARSED = "parsed"
STATUS_PARSED_EMPTY = "parsed_empty"
STATUS_UNRECOGNIZED = "unrecognized"
STATUS_PARSE_FAILURE = "parse_failure"
STATUS_FETCH_FAILED = "fetch_failed"
STATUS_WORKER_ERROR = "worker_error"

#: Only transport-ish failures are retried by ``--retry-failures``.
RETRYABLE_STATUSES = frozenset({STATUS_FETCH_FAILED, STATUS_WORKER_ERROR})

#: Parser refusals need parser/code changes and a new run intent, never a retry.
PARSER_REFUSAL_STATUSES = frozenset({STATUS_UNRECOGNIZED, STATUS_PARSE_FAILURE})

#: Every outcome that is not a recognized parse; a refusal blocks S5 publication.
REFUSAL_STATUSES = RETRYABLE_STATUSES | PARSER_REFUSAL_STATUSES

ALL_STATUSES = frozenset(
    {
        STATUS_PARSED,
        STATUS_PARSED_EMPTY,
        STATUS_UNRECOGNIZED,
        STATUS_PARSE_FAILURE,
        STATUS_FETCH_FAILED,
        STATUS_WORKER_ERROR,
    }
)


class AttemptValidationError(RuntimeError):
    """A chunk attempt's files or manifest failed validation."""


@dataclass(frozen=True, slots=True)
class AttemptManifest:
    """Everything needed to accept or reject one committed chunk attempt."""

    version: int
    chunk_id: str
    attempt_id: str
    run_id: str
    work_order_version: str
    parser_version: str
    outcome_schema_version: int
    entry_schema_version: int
    membership: tuple[str, ...]
    membership_digest: str
    outcomes_rows: int
    outcomes_sha256: str
    entries_rows: int
    entries_sha256: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "chunk_id": self.chunk_id,
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "work_order_version": self.work_order_version,
            "parser_version": self.parser_version,
            "outcome_schema_version": self.outcome_schema_version,
            "entry_schema_version": self.entry_schema_version,
            "membership": list(self.membership),
            "membership_digest": self.membership_digest,
            "outcomes_rows": self.outcomes_rows,
            "outcomes_sha256": self.outcomes_sha256,
            "entries_rows": self.entries_rows,
            "entries_sha256": self.entries_sha256,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AttemptManifest:
        membership = data["membership"]
        if not isinstance(membership, list):
            raise AttemptValidationError("manifest membership is not a list")
        return cls(
            version=int(data["version"]),
            chunk_id=str(data["chunk_id"]),
            attempt_id=str(data["attempt_id"]),
            run_id=str(data["run_id"]),
            work_order_version=str(data["work_order_version"]),
            parser_version=str(data["parser_version"]),
            outcome_schema_version=int(data["outcome_schema_version"]),
            entry_schema_version=int(data["entry_schema_version"]),
            membership=tuple(str(item) for item in membership),
            membership_digest=str(data["membership_digest"]),
            outcomes_rows=int(data["outcomes_rows"]),
            outcomes_sha256=str(data["outcomes_sha256"]),
            entries_rows=int(data["entries_rows"]),
            entries_sha256=str(data["entries_sha256"]),
            created_at=str(data["created_at"]),
        )


@dataclass(frozen=True, slots=True)
class ChunkValidation:
    """Whether a chunk's pointed attempt passed every resume check."""

    valid: bool
    attempt_id: str | None = None
    reason: str = ""
    manifest: AttemptManifest | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_attempt_id() -> str:
    """Return a fresh opaque attempt id; attempts are immutable once written."""
    return os.urandom(8).hex()


def _diagnostics_json(diagnostics: ParserDiagnostics | None) -> str:
    if diagnostics is None:
        return ""
    payload = {
        "items": [
            {
                "code": item.code,
                "row_key": list(item.row_key) if item.row_key else None,
                "detail": item.detail,
            }
            for item in diagnostics.items
        ],
        "suppressed_count": diagnostics.suppressed_count,
    }
    return canonical_json(payload)


def _empty_outcome(accession: str, index_url: str, status: str) -> dict[str, Any]:
    return {
        "accession": accession,
        "status": status,
        "index_url": index_url,
        "page_sha256": None,
        "response_size": None,
        "entry_count": 0,
        "xbrl_candidate_url": None,
        "bundle_url": None,
        "bundle_size": None,
        "diagnostics_json": "",
        "error_code": None,
        "error_detail": None,
    }


def outcome_row(
    result: Any,
    *,
    index_url: str,
    response_size: int | None = None,
) -> dict[str, Any]:
    """Project one typed worker result into a single outcomes.parquet row."""
    accession = str(result.accession)
    if isinstance(result, ParsedIndexPage):
        status = STATUS_PARSED if result.entries else STATUS_PARSED_EMPTY
        row = _empty_outcome(accession, index_url, status)
        row.update(
            page_sha256=result.page_sha256,
            response_size=response_size,
            entry_count=len(result.entries),
            xbrl_candidate_url=result.xbrl_candidate_url,
            bundle_url=result.bundle_url,
            bundle_size=result.bundle_size,
            diagnostics_json=_diagnostics_json(result.diagnostics),
        )
        return row
    if isinstance(result, UnrecognizedIndexPage):
        row = _empty_outcome(accession, index_url, STATUS_UNRECOGNIZED)
        row.update(
            page_sha256=result.page_sha256,
            response_size=response_size,
            diagnostics_json=_diagnostics_json(result.diagnostics),
        )
        return row
    if isinstance(result, IndexParseFailure):
        row = _empty_outcome(accession, index_url, STATUS_PARSE_FAILURE)
        row.update(
            page_sha256=result.page_sha256,
            response_size=response_size,
            diagnostics_json=_diagnostics_json(
                ParserDiagnostics((result.diagnostic,), 0)
            ),
            error_code=result.diagnostic.code,
            error_detail=result.diagnostic.detail,
        )
        return row
    if isinstance(result, IndexFetchFailure):
        row = _empty_outcome(accession, index_url, STATUS_FETCH_FAILED)
        row.update(error_code=result.code, error_detail=result.detail)
        return row
    if isinstance(result, IndexWorkerFailure):
        row = _empty_outcome(accession, index_url, result.code)
        row.update(error_code=result.code, error_detail=result.detail)
        return row
    raise TypeError(f"unsupported worker result type: {type(result).__name__}")


def _entry_row(entry: InventoryEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "accession": str(entry.accession),
        "table_kind": entry.table_kind,
        "row_ordinal": entry.row_ordinal,
        "sequence": entry.sequence,
        "document_type": entry.document_type,
        "document_label": entry.document_label,
        "description": entry.description,
        "filename": entry.filename,
        "href": entry.href,
        "archive_url": entry.archive_url,
        "byte_size": entry.byte_size,
    }


def entry_rows(result: Any) -> list[dict[str, Any]]:
    """Project one typed worker result into zero-or-more entries.parquet rows."""
    if isinstance(result, ParsedIndexPage):
        return [_entry_row(entry) for entry in result.entries]
    return []


def _columnar(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> dict[str, list]:
    return {field.name: [row.get(field.name) for row in rows] for field in schema}


class AttemptWriters:
    """Paired staged writers streaming one chunk attempt's two relations.

    Buffers are bounded so the coordinator never retains a cohort of results, and a
    crash mid-attempt leaves only a ``.tmp`` that resume discards wholesale.
    """

    _FLUSH_ROWS = 256

    def __init__(
        self, paths: InventoryRunPaths, chunk_id: str, attempt_id: str
    ) -> None:
        self._outcomes = StagedParquetWriter(
            paths.attempt_outcomes_path(chunk_id, attempt_id), OUTCOME_SCHEMA
        )
        self._entries = StagedParquetWriter(
            paths.attempt_entries_path(chunk_id, attempt_id), ENTRY_SCHEMA
        )
        self._outcome_buffer: list[dict[str, Any]] = []
        self._entry_buffer: list[dict[str, Any]] = []
        self._closed = False

    def add(
        self,
        outcome: Mapping[str, Any],
        entries: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        """Append one outcome row and its entry rows to the staged attempt."""
        if self._closed:
            raise RuntimeError("cannot write to a closed attempt")
        self._outcome_buffer.append(dict(outcome))
        self._entry_buffer.extend(dict(item) for item in entries)
        if len(self._outcome_buffer) >= self._FLUSH_ROWS:
            self._flush()

    def write_outcome_batch(self, batch: pa.RecordBatch | pa.Table) -> None:
        self._flush()
        self._outcomes.write_batch(batch)

    def write_entry_batch(self, batch: pa.RecordBatch | pa.Table) -> None:
        self._flush()
        self._entries.write_batch(batch)

    def _flush(self) -> None:
        if self._outcome_buffer:
            self._outcomes.write_batch(_columnar(self._outcome_buffer, OUTCOME_SCHEMA))
            self._outcome_buffer = []
        if self._entry_buffer:
            self._entries.write_batch(_columnar(self._entry_buffer, ENTRY_SCHEMA))
            self._entry_buffer = []

    def close(self) -> None:
        """Flush buffers and atomically promote both staging files to final paths."""
        if self._closed:
            return
        self._flush()
        self._outcomes.commit()
        self._entries.commit()
        self._closed = True


def advance_pointer(paths: InventoryRunPaths, chunk_id: str, attempt_id: str) -> None:
    """Atomically advance a chunk's pointer; this write is the commit marker."""
    payload = {
        "chunk_id": chunk_id,
        "attempt_id": attempt_id,
        "pointed_at": _now_iso(),
    }
    atomic_write_json(paths.chunk_pointer_path(chunk_id), payload, canonical=True)


def _validate_membership(
    outcomes_path: Path, entries_path: Path, membership: Sequence[str]
) -> None:
    con = connect()
    try:
        con.execute("CREATE TEMP TABLE expected (accession VARCHAR)")
        con.execute("INSERT INTO expected SELECT unnest(?)", [list(membership)])
        con.execute("CREATE TEMP TABLE actual_outcomes (accession VARCHAR)")
        con.execute(
            f"INSERT INTO actual_outcomes SELECT accession FROM "
            f"read_parquet({sql_path_list([str(outcomes_path)])})"
        )
        duplicate = con.execute(
            "SELECT accession FROM actual_outcomes GROUP BY accession "
            "HAVING count(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate is not None:
            raise AttemptValidationError("outcome accessions are not unique")
        mismatch = con.execute(
            "SELECT EXISTS (SELECT accession FROM actual_outcomes "
            "ANTI JOIN expected USING(accession)) OR EXISTS "
            "(SELECT accession FROM expected ANTI JOIN actual_outcomes USING(accession))"
        ).fetchone()[0]
        if mismatch:
            raise AttemptValidationError(
                "outcome accessions do not exactly match chunk membership"
            )
        entry_outside = con.execute(
            f"SELECT EXISTS (SELECT DISTINCT accession FROM "
            f"read_parquet({sql_path_list([str(entries_path)])}) e "
            "ANTI JOIN expected USING(accession))"
        ).fetchone()[0]
        if entry_outside:
            raise AttemptValidationError(
                "entry accessions fall outside chunk membership"
            )
    finally:
        con.close()


def finalize_attempt(
    paths: InventoryRunPaths,
    chunk_id: str,
    attempt_id: str,
    *,
    membership: Sequence[str],
    run: InventoryRunManifest,
) -> AttemptManifest:
    """Validate both Parquet files, write the attempt manifest, advance the pointer.

    Call only after :class:`AttemptWriters` has closed both files. The pointer is
    written last so a crash before this point leaves the previous commit usable.
    """
    outcomes_path = paths.attempt_outcomes_path(chunk_id, attempt_id)
    entries_path = paths.attempt_entries_path(chunk_id, attempt_id)
    if read_parquet_schema(outcomes_path) != OUTCOME_SCHEMA:
        raise AttemptValidationError(f"outcomes schema mismatch in {outcomes_path}")
    if read_parquet_schema(entries_path) != ENTRY_SCHEMA:
        raise AttemptValidationError(f"entries schema mismatch in {entries_path}")
    outcome_count = count_parquet_rows(outcomes_path)
    entry_count = count_parquet_rows(entries_path)
    ordered = tuple(sorted(membership))
    _validate_membership(outcomes_path, entries_path, ordered)
    manifest = AttemptManifest(
        version=ATTEMPT_MANIFEST_VERSION,
        chunk_id=chunk_id,
        attempt_id=attempt_id,
        run_id=run.run_id,
        work_order_version=run.work_order_version,
        parser_version=run.parser_version,
        outcome_schema_version=OUTCOME_SCHEMA_VERSION,
        entry_schema_version=ENTRY_SCHEMA_VERSION,
        membership=ordered,
        membership_digest=membership_digest(ordered),
        outcomes_rows=outcome_count,
        outcomes_sha256=file_sha256(outcomes_path),
        entries_rows=entry_count,
        entries_sha256=file_sha256(entries_path),
        created_at=_now_iso(),
    )
    atomic_write_json(
        paths.attempt_manifest_path(chunk_id, attempt_id),
        manifest.to_dict(),
        canonical=True,
    )
    advance_pointer(paths, chunk_id, attempt_id)
    return manifest


def read_attempt_manifest(
    paths: InventoryRunPaths, chunk_id: str, attempt_id: str
) -> AttemptManifest | None:
    """Read one attempt manifest, returning None when it is missing or malformed."""
    path = paths.attempt_manifest_path(chunk_id, attempt_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return AttemptManifest.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _read_pointer(paths: InventoryRunPaths, chunk_id: str) -> dict[str, Any] | None:
    path = paths.chunk_pointer_path(chunk_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _validate_files(
    paths: InventoryRunPaths,
    chunk_id: str,
    attempt_id: str,
    manifest: AttemptManifest,
) -> None:
    outcomes_path = paths.attempt_outcomes_path(chunk_id, attempt_id)
    entries_path = paths.attempt_entries_path(chunk_id, attempt_id)
    if not outcomes_path.is_file() or not entries_path.is_file():
        raise AttemptValidationError("attempt Parquet files are missing")
    if read_parquet_schema(outcomes_path) != OUTCOME_SCHEMA:
        raise AttemptValidationError("outcomes schema mismatch")
    if read_parquet_schema(entries_path) != ENTRY_SCHEMA:
        raise AttemptValidationError("entries schema mismatch")
    if count_parquet_rows(outcomes_path) != manifest.outcomes_rows:
        raise AttemptValidationError("outcome row count does not match manifest")
    if count_parquet_rows(entries_path) != manifest.entries_rows:
        raise AttemptValidationError("entry row count does not match manifest")
    if file_sha256(outcomes_path) != manifest.outcomes_sha256:
        raise AttemptValidationError("outcomes file digest does not match manifest")
    if file_sha256(entries_path) != manifest.entries_sha256:
        raise AttemptValidationError("entries file digest does not match manifest")
    _validate_membership(outcomes_path, entries_path, manifest.membership)


def validate_committed_chunk(
    paths: InventoryRunPaths,
    chunk_id: str,
    *,
    run: InventoryRunManifest,
    chunk: ChunkIdentity,
) -> ChunkValidation:
    """Return whether a chunk's pointed attempt is valid for resume without refetch.

    Any identity, version, membership, schema, row-count, or digest mismatch
    invalidates the chunk: it is recomputed as a whole.
    """
    pointer = _read_pointer(paths, chunk_id)
    if pointer is None:
        return ChunkValidation(False, None, "no chunk pointer")
    attempt_id = pointer.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        return ChunkValidation(False, None, "pointer names no attempt")
    try:
        manifest = read_attempt_manifest(paths, chunk_id, attempt_id)
    except ValueError:
        manifest = None
    if manifest is None:
        return ChunkValidation(
            False, attempt_id, "attempt manifest missing or malformed"
        )
    if manifest.run_id != run.run_id:
        return ChunkValidation(False, attempt_id, "run_id mismatch")
    if manifest.work_order_version != run.work_order_version:
        return ChunkValidation(False, attempt_id, "work_order_version mismatch")
    if manifest.parser_version != run.parser_version:
        return ChunkValidation(False, attempt_id, "parser_version mismatch")
    if manifest.outcome_schema_version != OUTCOME_SCHEMA_VERSION:
        return ChunkValidation(False, attempt_id, "outcome schema version mismatch")
    if manifest.entry_schema_version != ENTRY_SCHEMA_VERSION:
        return ChunkValidation(False, attempt_id, "entry schema version mismatch")
    if manifest.membership_digest != chunk.membership_digest:
        return ChunkValidation(False, attempt_id, "membership digest mismatch")
    if len(manifest.membership) != chunk.membership_count:
        return ChunkValidation(False, attempt_id, "membership count mismatch")
    if membership_digest(manifest.membership) != manifest.membership_digest:
        return ChunkValidation(False, attempt_id, "stored membership is corrupt")
    try:
        _validate_files(paths, chunk_id, attempt_id, manifest)
    except (AttemptValidationError, OSError, ValueError) as exc:
        return ChunkValidation(False, attempt_id, str(exc))
    return ChunkValidation(True, attempt_id, "", manifest)


def iter_outcome_rows(
    paths: InventoryRunPaths, chunk_id: str, attempt_id: str
) -> Iterator[dict[str, Any]]:
    parquet = pq.ParquetFile(paths.attempt_outcomes_path(chunk_id, attempt_id))
    for batch in parquet.iter_batches(batch_size=256):
        for index in range(batch.num_rows):
            yield {
                name: batch.column(column)[index].as_py()
                for column, name in enumerate(OUTCOME_SCHEMA.names)
            }


def split_retryable(
    outcome_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Split attempt outcomes into carry-forward rows and retryable accessions.

    Only ``fetch_failed`` and ``worker_error`` are retried; parser refusals and
    successes are carried forward unchanged.
    """
    carry = [
        dict(row) for row in outcome_rows if row.get("status") not in RETRYABLE_STATUSES
    ]
    retry = {
        str(row["accession"])
        for row in outcome_rows
        if row.get("status") in RETRYABLE_STATUSES
    }
    return carry, retry
