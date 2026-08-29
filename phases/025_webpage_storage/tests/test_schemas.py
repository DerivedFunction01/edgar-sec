from __future__ import annotations

import sqlite3
from importlib import import_module

from defs.sql import make_sql_executor

schemas = import_module("phases.025_webpage_storage.core.schemas")

BLOB_COLUMNS = schemas.BLOB_COLUMNS
build_blob = schemas.build_blob
build_occurrence = schemas.build_occurrence
create_partition_schema = schemas.create_partition_schema
decompress_payload = schemas.decompress_payload
doc_id = schemas.doc_id
occurrence_id = schemas.occurrence_id


def test_partition_schema_is_created_from_sql_ast(tmp_path):
    database = tmp_path / "partition.db"
    database.touch()
    executor = make_sql_executor(database, dialect="sqlite")
    create_partition_schema(executor)
    executor.close()

    connection = sqlite3.connect(database)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "document_blobs",
        "filing_occurrences",
        "_committed_chunks",
        "acquisition_failures",
    } <= tables
    columns = {
        row[1]: row[2]
        for row in connection.execute("PRAGMA table_info(document_blobs)")
    }
    assert tuple(columns) == BLOB_COLUMNS
    assert columns["raw_payload"] == "BLOB"
    assert columns["byte_size"] == "INTEGER"
    indexes = {
        row[1] for row in connection.execute("PRAGMA index_list(filing_occurrences)")
    }
    assert "idx_occurrences_cik" in indexes
    assert "idx_occurrences_accession" in indexes
    connection.close()


def test_content_addressing_and_zstd_round_trip():
    raw = b"legacy SEC filing bytes\x00\xff"
    blob = build_blob("000000000100000001", "d10k.htm", raw)
    assert blob.doc_id == doc_id("000000000100000001", "d10k.htm")
    assert blob.byte_size == len(raw)
    assert decompress_payload(blob.raw_payload) == raw
    assert blob.mime_type == "text/html"

    occurrence = build_occurrence(
        "0000000001",
        "000000000100000001",
        "d10k.htm",
        "10-K",
        "2024-01-02",
        "2023-12-31",
    )
    assert occurrence.occurrence_id == occurrence_id(
        "0000000001", "000000000100000001", "d10k.htm"
    )
    assert occurrence.doc_id == blob.doc_id
