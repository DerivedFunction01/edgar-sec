"""Physical SQLite schemas, typed records, and content addressing.

This module is the schema contract for the whole phase: workers, the
partition merger, the fetcher, and the pipeline all derive their table
shapes from the DDL builders here. All statements are expressed as
``defs.sql`` AST nodes so the sql-boundary policy holds; nothing in this
module opens a driver connection itself.
"""

from __future__ import annotations

import hashlib
import json
import threading
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

from .records import (
    AcquisitionFailure,
    CommittedChunk,
    DocumentLocator,
    FetchResult,
    FilingOccurrence,
    NormalizationFailure,
    NormalizedDocument,
    RawDocumentBlob,
)

SCHEMA_VERSION = 2
NORMALIZED_SCHEMA_VERSION = 1
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
NORMALIZED_DOCUMENTS_TABLE = "normalized_documents"
NORMALIZATION_FAILURES_TABLE = "normalization_failures"

BLOB_COLUMNS = (
    "doc_id",
    "accession",
    "document_path",
    "byte_size",
    "mime_type",
    "raw_payload",
    "raw_payload_sha256",
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
COMMITTED_CHUNK_COLUMNS = (
    "chunk_id",
    "record_count",
    "worker_id",
    "committed_at",
    "processor_fingerprint",
    "normalized_schema_version",
)
ACQUISITION_FAILURE_COLUMNS = (
    "doc_id",
    "accession",
    "document_path",
    "status",
    "error_message",
    "attempted_at",
)
NORMALIZED_DOCUMENT_COLUMNS = (
    "normalized_artifact_id",
    "source_doc_id",
    "byte_size",
    "normalized_payload",
    "payload_sha256",
    "mime_type",
    "representation",
    "processor_fingerprint",
    "schema_version",
    "processor_metadata",
)
NORMALIZATION_FAILURE_COLUMNS = (
    "source_doc_id",
    "processor_fingerprint",
    "schema_version",
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
            ColumnDef("raw_payload_sha256", ColumnType.TEXT, (NotNull(),)),
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
            ColumnDef("processor_fingerprint", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("normalized_schema_version", ColumnType.INT, (NotNull(),)),
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


def normalized_documents_ddl() -> CreateTable:
    return CreateTable(
        table=NORMALIZED_DOCUMENTS_TABLE,
        columns=(
            ColumnDef(
                "normalized_artifact_id", ColumnType.TEXT, (PrimaryKey(), NotNull())
            ),
            ColumnDef(
                "source_doc_id",
                ColumnType.TEXT,
                (NotNull(), References(DOCUMENT_BLOBS_TABLE, ("doc_id",))),
            ),
            ColumnDef("byte_size", ColumnType.INT, (NotNull(),)),
            ColumnDef("normalized_payload", ColumnType.BLOB, (NotNull(),)),
            ColumnDef("payload_sha256", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("mime_type", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("representation", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("processor_fingerprint", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("schema_version", ColumnType.INT, (NotNull(),)),
            ColumnDef("processor_metadata", ColumnType.TEXT, (NotNull(),)),
        ),
    )


def normalization_failures_ddl() -> CreateTable:
    return CreateTable(
        table=NORMALIZATION_FAILURES_TABLE,
        columns=(
            ColumnDef("source_doc_id", ColumnType.TEXT, (PrimaryKey(), NotNull())),
            ColumnDef("processor_fingerprint", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("schema_version", ColumnType.INT, (NotNull(),)),
            ColumnDef("error_message", ColumnType.TEXT, (NotNull(),)),
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
        normalized_documents_ddl(),
        normalization_failures_ddl(),
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
        raw_payload_sha256=hashlib.sha256(raw).hexdigest(),
    )


def normalized_artifact_id(
    raw_digest: str,
    processor_fingerprint: str,
    schema_version: int = NORMALIZED_SCHEMA_VERSION,
) -> str:
    return hashlib.sha256(
        f"{raw_digest}:{processor_fingerprint}:{schema_version}".encode()
    ).hexdigest()


def deterministic_metadata(metadata: dict[str, object]) -> str:
    return json.dumps(
        metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=True
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
    "NORMALIZATION_FAILURES_TABLE",
    "NORMALIZATION_FAILURE_COLUMNS",
    "NORMALIZED_DOCUMENTS_TABLE",
    "NORMALIZED_DOCUMENT_COLUMNS",
    "NORMALIZED_SCHEMA_VERSION",
    "OCCURRENCE_COLUMNS",
    "SCHEMA_VERSION",
    "ZSTD_COMPRESSION_LEVEL",
    "AcquisitionFailure",
    "CommittedChunk",
    "DocumentLocator",
    "FetchResult",
    "FilingOccurrence",
    "NormalizationFailure",
    "NormalizedDocument",
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
    "deterministic_metadata",
    "doc_id",
    "document_blobs_ddl",
    "filing_occurrences_ddl",
    "normalization_failures_ddl",
    "normalized_artifact_id",
    "normalized_documents_ddl",
    "occurrence_id",
    "partition_ddl",
    "partition_indexes",
    "partition_tables_ddl",
)
