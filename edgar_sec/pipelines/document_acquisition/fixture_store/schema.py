"""Schema and integrity checks for acquisition parser-body fixtures."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

import edgar_sec.foundation.runtime.fixtures as foundation_fixtures
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.infra.storage.duckdb import sql_literal
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixturePlanPin,
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths

SCHEMA_VERSION = 3
FIXTURE_KIND = "document_acquisition.parser_bodies"
_FIXTURE_DETAIL_KEYS = {
    "store_schema_version",
    "target_plan_id",
    "target_plan_digest",
    "target_plan_schema_version",
}
_TABLES = frozenset({"fixture_meta", "body_blobs", "captures", "lazy_indexes", "cases"})
_CAPTURE_COLUMNS = (
    "capture_id",
    "target_plan_id",
    "target_plan_digest",
    "target_plan_schema_version",
    "captured_at_utc",
)
_LAZY_INDEX_COLUMNS = ("accession", "index_url", "body_sha256", "byte_size")
_CASE_COLUMNS = (
    "capture_id",
    "target_id",
    "inventory_entry_id",
    "selection_source",
    "index_sha256",
    "accession",
    "form",
    "request_id",
    "target_role",
    "target_type",
    "source_origin",
    "retrieval_mode",
    "target_url",
    "sequence",
    "selected_filename",
    "body_sha256",
    "byte_size",
)
_EXPECTED_COLUMNS = {
    "fixture_meta": ("key", "value"),
    "body_blobs": (
        "body_id",
        "body_sha256",
        "byte_size",
        "storage_codec",
        "stored_sha256",
        "stored_byte_size",
        "compressed_body",
    ),
    "captures": _CAPTURE_COLUMNS,
    "lazy_indexes": _LAZY_INDEX_COLUMNS,
    "cases": _CASE_COLUMNS,
}
_IMMUTABILITY_TRIGGERS = frozenset(
    {
        "immutable_fixture_meta_update",
        "immutable_fixture_meta_delete",
        "immutable_body_blob_update",
        "immutable_body_blob_delete",
        "immutable_capture_update",
        "immutable_capture_delete",
        "immutable_lazy_index_update",
        "immutable_lazy_index_delete",
        "immutable_case_update",
        "immutable_case_delete",
    }
)
_SCHEMA = (
    """CREATE TABLE fixture_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE body_blobs (
        body_id INTEGER PRIMARY KEY,
        body_sha256 TEXT NOT NULL UNIQUE,
        byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
        storage_codec TEXT NOT NULL CHECK (storage_codec = 'zstd'),
        stored_sha256 TEXT NOT NULL,
        stored_byte_size INTEGER NOT NULL CHECK (stored_byte_size >= 0),
        compressed_body BLOB NOT NULL,
        CHECK (length(body_sha256) = 64 AND body_sha256 NOT GLOB '*[^0-9a-f]*'),
        CHECK (length(stored_sha256) = 64 AND stored_sha256 NOT GLOB '*[^0-9a-f]*'),
        CHECK (length(compressed_body) = stored_byte_size),
        UNIQUE (body_sha256, byte_size)
    )""",
    """CREATE TABLE captures (
        capture_id TEXT PRIMARY KEY,
        target_plan_id TEXT NOT NULL,
        target_plan_digest TEXT NOT NULL,
        target_plan_schema_version INTEGER NOT NULL,
        captured_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE lazy_indexes (
        accession TEXT PRIMARY KEY,
        index_url TEXT NOT NULL,
        body_sha256 TEXT NOT NULL,
        byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
        FOREIGN KEY (body_sha256, byte_size) REFERENCES body_blobs(body_sha256, byte_size)
    )""",
    """CREATE TABLE cases (
        capture_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        inventory_entry_id TEXT,
        selection_source TEXT NOT NULL CHECK (selection_source IN ('planned_source', 'inventory_index', 'fixture_lazy_index')),
        index_sha256 TEXT,
        accession TEXT NOT NULL,
        form TEXT NOT NULL,
        request_id TEXT NOT NULL,
        target_role TEXT NOT NULL,
        target_type TEXT NOT NULL,
        source_origin TEXT NOT NULL CHECK (source_origin IN ('inventory_index', 'catalog_direct')),
        retrieval_mode TEXT NOT NULL CHECK (retrieval_mode IN ('direct_url', 'bundle_sequence')),
        target_url TEXT,
        sequence INTEGER,
        selected_filename TEXT NOT NULL CHECK (length(selected_filename) > 0),
        body_sha256 TEXT NOT NULL,
        byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
        PRIMARY KEY (capture_id, target_id),
        FOREIGN KEY (capture_id) REFERENCES captures(capture_id),
        FOREIGN KEY (body_sha256, byte_size) REFERENCES body_blobs(body_sha256, byte_size),
        FOREIGN KEY (index_sha256) REFERENCES body_blobs(body_sha256),
        CHECK ((selection_source = 'fixture_lazy_index' AND index_sha256 IS NOT NULL) OR
            (selection_source != 'fixture_lazy_index' AND index_sha256 IS NULL)),
        CHECK ((retrieval_mode = 'direct_url' AND sequence IS NULL) OR
            (retrieval_mode = 'bundle_sequence' AND sequence IS NOT NULL AND sequence > 0)),
        CHECK (length(body_sha256) = 64 AND body_sha256 NOT GLOB '*[^0-9a-f]*')
    )""",
    """CREATE TRIGGER immutable_fixture_meta_update BEFORE UPDATE ON fixture_meta
        BEGIN SELECT RAISE(ABORT, 'fixture metadata is immutable'); END""",
    """CREATE TRIGGER immutable_fixture_meta_delete BEFORE DELETE ON fixture_meta
        BEGIN SELECT RAISE(ABORT, 'fixture metadata is immutable'); END""",
    """CREATE TRIGGER immutable_body_blob_update BEFORE UPDATE ON body_blobs
        BEGIN SELECT RAISE(ABORT, 'fixture bodies are immutable'); END""",
    """CREATE TRIGGER immutable_body_blob_delete BEFORE DELETE ON body_blobs
        BEGIN SELECT RAISE(ABORT, 'fixture bodies are immutable'); END""",
    """CREATE TRIGGER immutable_capture_update BEFORE UPDATE ON captures
        BEGIN SELECT RAISE(ABORT, 'fixture captures are immutable'); END""",
    """CREATE TRIGGER immutable_capture_delete BEFORE DELETE ON captures
        BEGIN SELECT RAISE(ABORT, 'fixture captures are immutable'); END""",
    """CREATE TRIGGER immutable_lazy_index_update BEFORE UPDATE ON lazy_indexes
        BEGIN SELECT RAISE(ABORT, 'fixture lazy indexes are immutable'); END""",
    """CREATE TRIGGER immutable_lazy_index_delete BEFORE DELETE ON lazy_indexes
        BEGIN SELECT RAISE(ABORT, 'fixture lazy indexes are immutable'); END""",
    """CREATE TRIGGER immutable_case_update BEFORE UPDATE ON cases
        BEGIN SELECT RAISE(ABORT, 'fixture cases are immutable'); END""",
    """CREATE TRIGGER immutable_case_delete BEFORE DELETE ON cases
        BEGIN SELECT RAISE(ABORT, 'fixture cases are immutable'); END""",
)


def fixture_paths(
    paths: AcquisitionPaths, fixture_id: str
) -> foundation_fixtures.FixturePaths:
    return paths.fixture_paths(fixture_id)


def connect(database: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{quote(str(database.resolve()), safe='/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise FixtureStoreError("SQLite foreign-key enforcement is unavailable")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    for statement in _SCHEMA:
        connection.execute(statement)
    connection.execute(f"PRAGMA user_version = {sql_literal(str(SCHEMA_VERSION))}")


def _validate_manifest(
    fixture: foundation_fixtures.FixturePaths,
) -> FixturePlanPin:
    try:
        raw = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
        envelope = foundation_fixtures.FixtureManifestEnvelope.from_mapping(raw)
        schema_version = envelope.details.get("store_schema_version")
        plan_id = envelope.details.get("target_plan_id")
        plan_digest = envelope.details.get("target_plan_digest")
        plan_schema_version = envelope.details.get("target_plan_schema_version")
        if (
            envelope.fixture_kind != FIXTURE_KIND
            or envelope.fixture_id != fixture.fixture_id
            or envelope.storage_format != "sqlite"
            or envelope.storage_path != fixture.storage_filename
            or envelope.created_at != envelope.updated_at
            or set(envelope.details) != _FIXTURE_DETAIL_KEYS
            or type(schema_version) is not int
            or schema_version != SCHEMA_VERSION
            or not isinstance(plan_id, str)
            or not plan_id
            or not is_sha256_hex_digest(plan_digest)
            or type(plan_schema_version) is not int
            or plan_schema_version < 1
        ):
            raise ValueError("fixture descriptor does not match the parser-body store")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise FixtureStoreError(
            f"invalid fixture manifest: {fixture.manifest_path}"
        ) from error
    return FixturePlanPin(plan_id, plan_digest, plan_schema_version)


def validate_database(
    connection: sqlite3.Connection,
    database: Path,
    manifest_version: int,
    plan_pin: FixturePlanPin,
) -> None:
    database_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if database_version != SCHEMA_VERSION:
        raise FixtureStoreError("unsupported acquisition fixture schema version")
    if database_version != manifest_version:
        raise FixtureStoreError(
            "fixture manifest and SQLite schema versions do not match"
        )
    tables = frozenset(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    if tables != _TABLES:
        raise FixtureStoreError(f"not an acquisition fixture database: {database}")
    for table, expected in _EXPECTED_COLUMNS.items():
        actual = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM pragma_table_info(?)", (table,)
            )
        )
        if actual != expected:
            raise FixtureStoreError(f"invalid {table} schema in {database}")
    triggers = frozenset(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    )
    if triggers != _IMMUTABILITY_TRIGGERS:
        raise FixtureStoreError(f"invalid fixture immutability triggers in {database}")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise FixtureStoreError(f"corrupt acquisition fixture database: {database}")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise FixtureStoreError(f"invalid fixture references: {database}")
    metadata = dict(connection.execute("SELECT key, value FROM fixture_meta"))
    if metadata != {
        "target_plan_id": plan_pin.target_plan_id,
        "target_plan_digest": plan_pin.target_plan_digest,
        "target_plan_schema_version": str(plan_pin.target_plan_schema_version),
    }:
        raise FixtureStoreError("fixture plan pin differs from its manifest")


def open_fixture(
    paths: AcquisitionPaths, fixture_id: str, *, readonly: bool
) -> tuple[foundation_fixtures.FixturePaths, sqlite3.Connection]:
    fixture = fixture_paths(paths, fixture_id)
    if not fixture.manifest_path.is_file() or not fixture.storage_path.is_file():
        raise FixtureStoreError(f"fixture is missing or incomplete: {fixture.root}")
    plan_pin = _validate_manifest(fixture)
    connection = connect(fixture.storage_path, readonly=readonly)
    try:
        validate_database(connection, fixture.storage_path, SCHEMA_VERSION, plan_pin)
    except Exception:
        connection.close()
        raise
    return fixture, connection


def fixture_plan_pin(paths: AcquisitionPaths, fixture_id: str) -> FixturePlanPin:
    fixture, connection = open_fixture(paths, fixture_id, readonly=True)
    try:
        return _validate_manifest(fixture)
    finally:
        connection.close()
