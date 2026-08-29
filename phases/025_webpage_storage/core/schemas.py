"""Physical SQLite schemas, typed records, and content addressing.

This module is the schema contract for the whole phase: workers, the
partition merger, the fetcher, and the pipeline all derive their table
shapes from the DDL builders here. All statements are expressed as
``defs.sql`` AST nodes so the sql-boundary policy holds; nothing in this
module opens a driver connection itself.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

import zstandard

from defs.sql import (
    ColumnDef,
    ColumnType,
    CompiledQuery,
    CreateIndex,
    CreateTable,
    DefaultCurrentTimestamp,
    IndexColumn,
    NotNull,
    PrimaryKey,
    QueryCompiler,
    References,
    SqlDialect,
    Statement,
    col,
)

SCHEMA_VERSION = 1
ZSTD_COMPRESSION_LEVEL = 3

_thread_local = threading.local()


def _get_compressor(level: int = ZSTD_COMPRESSION_LEVEL) -> zstandard.ZstdCompressor:
    compressor = getattr(_thread_local, "compressor", None)
    current_level = getattr(_thread_local, "compressor_level", None)
    if compressor is None or current_level != level:
        compressor = zstandard.ZstdCompressor(level=level)
        _thread_local.compressor = compressor
        _thread_local.compressor_level = level
    return compressor


def _get_decompressor() -> zstandard.ZstdDecompressor:
    decompressor = getattr(_thread_local, "decompressor", None)
    if decompressor is None:
        decompressor = zstandard.ZstdDecompressor()
        _thread_local.decompressor = decompressor
    return decompressor


DOCUMENT_BLOBS_TABLE = "document_blobs"
FILING_OCCURRENCES_TABLE = "filing_occurrences"
COMMITTED_CHUNKS_TABLE = "_committed_chunks"
ACQUISITION_FAILURES_TABLE = "acquisition_failures"

BLOB_COLUMNS = (
    "doc_id",
    "accession",
    "document_path",
    "byte_size",
    "mime_type",
    "raw_payload",
)
OCCURRENCE_COLUMNS = (
    "occurrence_id",
    "source_cik",
    "accession",
    "document_path",
    "form",
    "filing_date",
    "report_date",
    "doc_id",
)
COMMITTED_CHUNK_COLUMNS = ("chunk_id", "record_count", "worker_id", "committed_at")
ACQUISITION_FAILURE_COLUMNS = (
    "doc_id",
    "accession",
    "document_path",
    "status",
    "error_message",
    "attempted_at",
)

MIME_HTML = "text/html"
MIME_TEXT = "text/plain"
MIME_XML = "text/xml"
MIME_BINARY = "application/octet-stream"

_MIME_BY_SUFFIX = {
    ".htm": MIME_HTML,
    ".html": MIME_HTML,
    ".xhtml": MIME_HTML,
    ".txt": MIME_TEXT,
    ".xml": MIME_XML,
}


# ----------------------------------------------------------------- records


@dataclass(frozen=True, slots=True)
class RawDocumentBlob:
    """One deduplicated compressed raw payload."""

    doc_id: str
    accession: str
    document_path: str
    byte_size: int
    mime_type: str
    raw_payload: bytes

    def to_row(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> RawDocumentBlob:
        return cls(
            doc_id=str(row["doc_id"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            byte_size=int(row["byte_size"]),
            mime_type=str(row["mime_type"]),
            raw_payload=bytes(row["raw_payload"]),
        )


@dataclass(frozen=True, slots=True)
class FilingOccurrence:
    """Provenance link from one corporate occurrence to a stored blob."""

    occurrence_id: str
    source_cik: str
    accession: str
    document_path: str
    form: str
    filing_date: str
    report_date: str | None
    doc_id: str

    def to_row(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> FilingOccurrence:
        report_date = row["report_date"]
        return cls(
            occurrence_id=str(row["occurrence_id"]),
            source_cik=str(row["source_cik"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            form=str(row["form"]),
            filing_date=str(row["filing_date"]),
            report_date=None if report_date is None else str(report_date),
            doc_id=str(row["doc_id"]),
        )


@dataclass(frozen=True, slots=True)
class CommittedChunk:
    """Resumability audit row for one merged worker chunk."""

    chunk_id: str
    record_count: int
    worker_id: str
    committed_at: str

    def to_row(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> CommittedChunk:
        return cls(
            chunk_id=str(row["chunk_id"]),
            record_count=int(row["record_count"]),
            worker_id=str(row["worker_id"]),
            committed_at=str(row["committed_at"]),
        )


@dataclass(frozen=True, slots=True)
class AcquisitionFailure:
    """A document acquisition failure or missing payload record."""

    doc_id: str
    accession: str
    document_path: str
    status: str
    error_message: str | None
    attempted_at: str

    def to_row(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict) -> AcquisitionFailure:
        err = row.get("error_message")
        return cls(
            doc_id=str(row["doc_id"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            status=str(row["status"]),
            error_message=None if err is None else str(err),
            attempted_at=str(row["attempted_at"]),
        )


@dataclass(frozen=True, slots=True)
class DocumentLocator:
    """One unique pre-capture locator from a Phase 02 target plan."""

    locator_key: str
    accession: str
    document_path: str
    archive_url: str
    form: str = ""


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Outcome of one acquisition attempt for a locator."""

    locator: DocumentLocator
    payload: bytes | None
    status: str  # "ok" | "missing" | "failed"
    error: str | None = None


# --------------------------------------------------------------------- DDL


def document_blobs_ddl() -> CreateTable:
    return CreateTable(
        table=DOCUMENT_BLOBS_TABLE,
        columns=(
            ColumnDef("doc_id", ColumnType.TEXT, (PrimaryKey(), NotNull())),
            ColumnDef("accession", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("document_path", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("byte_size", ColumnType.INT, (NotNull(),)),
            ColumnDef("mime_type", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("raw_payload", ColumnType.BLOB, (NotNull(),)),
        ),
    )


def filing_occurrences_ddl() -> CreateTable:
    return CreateTable(
        table=FILING_OCCURRENCES_TABLE,
        columns=(
            ColumnDef("occurrence_id", ColumnType.TEXT, (PrimaryKey(), NotNull())),
            ColumnDef("source_cik", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("accession", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("document_path", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("form", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("filing_date", ColumnType.TIMESTAMP, (NotNull(),)),
            ColumnDef("report_date", ColumnType.TIMESTAMP),
            ColumnDef(
                "doc_id",
                ColumnType.TEXT,
                (NotNull(), References(DOCUMENT_BLOBS_TABLE, ("doc_id",))),
            ),
        ),
    )


def committed_chunks_ddl() -> CreateTable:
    return CreateTable(
        table=COMMITTED_CHUNKS_TABLE,
        columns=(
            ColumnDef("chunk_id", ColumnType.TEXT, (PrimaryKey(), NotNull())),
            ColumnDef("record_count", ColumnType.INT, (NotNull(),)),
            ColumnDef("worker_id", ColumnType.TEXT, (NotNull(),)),
            ColumnDef(
                "committed_at",
                ColumnType.TIMESTAMP,
                (NotNull(), DefaultCurrentTimestamp()),
            ),
        ),
    )


def acquisition_failures_ddl() -> CreateTable:
    return CreateTable(
        table=ACQUISITION_FAILURES_TABLE,
        columns=(
            ColumnDef("doc_id", ColumnType.TEXT, (PrimaryKey(), NotNull())),
            ColumnDef("accession", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("document_path", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("status", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("error_message", ColumnType.TEXT),
            ColumnDef(
                "attempted_at",
                ColumnType.TIMESTAMP,
                (NotNull(), DefaultCurrentTimestamp()),
            ),
        ),
    )


def partition_indexes() -> tuple[CreateIndex, ...]:
    return (
        CreateIndex(
            name="idx_occurrences_cik",
            table=FILING_OCCURRENCES_TABLE,
            columns=(IndexColumn(col("source_cik")),),
        ),
        CreateIndex(
            name="idx_occurrences_accession",
            table=FILING_OCCURRENCES_TABLE,
            columns=(IndexColumn(col("accession")),),
        ),
        CreateIndex(
            name="idx_occurrences_form_date",
            table=FILING_OCCURRENCES_TABLE,
            columns=(IndexColumn(col("form")), IndexColumn(col("filing_date"))),
        ),
        CreateIndex(
            name="idx_blobs_accession",
            table=DOCUMENT_BLOBS_TABLE,
            columns=(IndexColumn(col("accession")),),
        ),
    )


def partition_tables_ddl() -> tuple[Statement, ...]:
    return (
        document_blobs_ddl(),
        filing_occurrences_ddl(),
        committed_chunks_ddl(),
        acquisition_failures_ddl(),
    )


def partition_ddl() -> tuple[Statement, ...]:
    return (
        *partition_tables_ddl(),
        *partition_indexes(),
    )


def chunk_ddl() -> tuple[Statement, ...]:
    return partition_tables_ddl()


def compile_schema(
    statements: tuple[Statement, ...] | list[Statement],
    dialect: SqlDialect = SqlDialect.SQLITE,
) -> tuple[CompiledQuery, ...]:
    compiler = QueryCompiler(dialect)
    return tuple(compiler.compile(statement) for statement in statements)


def create_schema(executor, statements) -> None:
    """Create the given DDL on an open SQLite executor (idempotent)."""
    for query in compile_schema(statements):
        executor.exec(query)


def create_partition_schema(executor) -> None:
    create_schema(executor, partition_ddl())


def create_partition_indexes(executor) -> None:
    create_schema(executor, partition_indexes())


def create_chunk_schema(executor) -> None:
    create_schema(executor, chunk_ddl())


# ------------------------------------------------- content addressing


def doc_id(accession: str, document_path: str) -> str:
    """Content address of one archived document."""
    return hashlib.sha256(f"{accession}/{document_path}".encode()).hexdigest()


def occurrence_id(source_cik: str, accession: str, document_path: str) -> str:
    """Identity of one corporate occurrence pointing at a stored blob."""
    key = f"{source_cik}{accession}{document_path}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def compress_payload(raw: bytes, level: int = ZSTD_COMPRESSION_LEVEL) -> bytes:
    return _get_compressor(level=level).compress(raw)


def decompress_payload(payload: bytes) -> bytes:
    return _get_decompressor().decompress(payload)


def detect_mime(document_path: str) -> str:
    suffix = PurePosixPath(document_path).suffix.lower()
    return _MIME_BY_SUFFIX.get(suffix, MIME_BINARY)


def build_blob(
    accession: str, document_path: str, raw: bytes, level: int = ZSTD_COMPRESSION_LEVEL
) -> RawDocumentBlob:
    """Compress one raw payload into a content-addressed record."""
    return RawDocumentBlob(
        doc_id=doc_id(accession, document_path),
        accession=accession,
        document_path=document_path,
        byte_size=len(raw),
        mime_type=detect_mime(document_path),
        raw_payload=compress_payload(raw, level=level),
    )


def build_occurrence(
    source_cik: str,
    accession: str,
    document_path: str,
    form: str,
    filing_date: str,
    report_date: str | None,
) -> FilingOccurrence:
    return FilingOccurrence(
        occurrence_id=occurrence_id(source_cik, accession, document_path),
        source_cik=source_cik,
        accession=accession,
        document_path=document_path,
        form=form,
        filing_date=filing_date,
        report_date=report_date,
        doc_id=doc_id(accession, document_path),
    )


__all__ = (
    "ACQUISITION_FAILURES_TABLE",
    "ACQUISITION_FAILURE_COLUMNS",
    "BLOB_COLUMNS",
    "COMMITTED_CHUNKS_TABLE",
    "COMMITTED_CHUNK_COLUMNS",
    "DOCUMENT_BLOBS_TABLE",
    "FILING_OCCURRENCES_TABLE",
    "MIME_BINARY",
    "MIME_HTML",
    "MIME_TEXT",
    "MIME_XML",
    "OCCURRENCE_COLUMNS",
    "SCHEMA_VERSION",
    "ZSTD_COMPRESSION_LEVEL",
    "AcquisitionFailure",
    "CommittedChunk",
    "DocumentLocator",
    "FetchResult",
    "FilingOccurrence",
    "RawDocumentBlob",
    "acquisition_failures_ddl",
    "build_blob",
    "build_occurrence",
    "chunk_ddl",
    "committed_chunks_ddl",
    "compile_schema",
    "compress_payload",
    "create_chunk_schema",
    "create_partition_indexes",
    "create_partition_schema",
    "create_schema",
    "decompress_payload",
    "detect_mime",
    "doc_id",
    "document_blobs_ddl",
    "filing_occurrences_ddl",
    "occurrence_id",
    "partition_ddl",
    "partition_indexes",
    "partition_tables_ddl",
)
