"""S9 fixture SQLite schema, locations, and integrity checks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

import edgar_sec.foundation.runtime.fixtures as foundation_fixtures
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)

SCHEMA_VERSION = 2
FIXTURE_KIND = "document_acquisition.source_responses"
CHUNK_SIZE = 64 * 1024

_TABLES = frozenset({"fixture_meta", "response_bodies", "captures", "cases"})
_CAPTURE_COLUMNS = (
    "capture_id",
    "run_id",
    "target_plan_id",
    "target_plan_digest",
    "target_plan_schema_version",
    "inventory_snapshot_id",
    "inventory_snapshot_digest",
    "captured_at_utc",
)
_CASE_COLUMNS = (
    "capture_id",
    "target_id",
    "attempt_id",
    "accession",
    "form",
    "request_id",
    "target_role",
    "target_type",
    "optional",
    "catalog_direct_selection",
    "source_origin",
    "target_status",
    "retrieval_mode",
    "target_url",
    "final_url",
    "sequence",
    "acquisition_status",
    "error_code",
    "response_sha256",
    "index_response_sha256",
    "selected_response_sha256",
    "resolution_schema_version",
    "screen_kind",
    "screen_result",
    "evaluator_version",
    "index_parser_version",
    "matching_entry_ids_json",
    "selected_sequence",
    "selected_retrieval_mode",
    "selected_url",
    "source_byte_size",
    "selected_sha256",
    "selected_byte_size",
    "selected_filename",
    "content_type",
    "content_encoding",
)
_EXPECTED_COLUMNS = {
    "fixture_meta": ("key", "value"),
    "response_bodies": (
        "body_id",
        "response_sha256",
        "byte_size",
        "storage_codec",
        "stored_sha256",
        "stored_byte_size",
        "compressed_body",
    ),
    "captures": _CAPTURE_COLUMNS,
    "cases": _CASE_COLUMNS,
}
_IMMUTABILITY_TRIGGERS = frozenset(
    {
        "immutable_response_update",
        "immutable_response_delete",
        "immutable_capture_update",
        "immutable_capture_delete",
        "immutable_case_update",
        "immutable_case_delete",
    }
)

_SCHEMA = (
    """CREATE TABLE fixture_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE response_bodies (
        body_id INTEGER PRIMARY KEY,
        response_sha256 TEXT NOT NULL UNIQUE,
        byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
        storage_codec TEXT NOT NULL CHECK (storage_codec = 'zstd'),
        stored_sha256 TEXT NOT NULL,
        stored_byte_size INTEGER NOT NULL CHECK (stored_byte_size >= 0),
        compressed_body BLOB NOT NULL,
        CHECK (length(response_sha256) = 64 AND response_sha256 NOT GLOB '*[^0-9a-f]*'),
        CHECK (length(stored_sha256) = 64 AND stored_sha256 NOT GLOB '*[^0-9a-f]*'),
        CHECK (length(compressed_body) = stored_byte_size),
        UNIQUE (response_sha256, byte_size)
    )""",
    """CREATE TABLE captures (
        capture_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        target_plan_id TEXT NOT NULL,
        target_plan_digest TEXT NOT NULL,
        target_plan_schema_version TEXT NOT NULL,
        inventory_snapshot_id TEXT,
        inventory_snapshot_digest TEXT,
        captured_at_utc TEXT NOT NULL,
        CHECK ((inventory_snapshot_id IS NULL) = (inventory_snapshot_digest IS NULL))
    )""",
    """CREATE TABLE cases (
        capture_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        accession TEXT NOT NULL,
        form TEXT NOT NULL,
        request_id TEXT NOT NULL,
        target_role TEXT NOT NULL,
        target_type TEXT NOT NULL,
        optional INTEGER NOT NULL CHECK (optional IN (0, 1)),
        catalog_direct_selection TEXT CHECK (catalog_direct_selection IS NULL OR catalog_direct_selection IN ('submitted_primary', 'exact_form_with_lazy_index')),
        source_origin TEXT NOT NULL CHECK (source_origin IN ('inventory_index', 'catalog_direct')),
        target_status TEXT NOT NULL CHECK (target_status = 'matched'),
        retrieval_mode TEXT NOT NULL CHECK (retrieval_mode IN ('direct_url', 'bundle_sequence')),
        target_url TEXT,
        final_url TEXT,
        sequence INTEGER,
        acquisition_status TEXT NOT NULL CHECK (acquisition_status IN ('acquired', 'not_filed', 'required_missing', 'ambiguous', 'failed')),
        error_code TEXT,
        response_sha256 TEXT,
        index_response_sha256 TEXT,
        selected_response_sha256 TEXT,
        resolution_schema_version TEXT,
        screen_kind TEXT,
        screen_result TEXT,
        evaluator_version TEXT,
        index_parser_version TEXT,
        matching_entry_ids_json TEXT,
        selected_sequence INTEGER,
        selected_retrieval_mode TEXT,
        selected_url TEXT,
        source_byte_size INTEGER CHECK (source_byte_size IS NULL OR source_byte_size >= 0),
        selected_sha256 TEXT,
        selected_byte_size INTEGER CHECK (selected_byte_size IS NULL OR selected_byte_size >= 0),
        selected_filename TEXT,
        content_type TEXT,
        content_encoding TEXT,
        PRIMARY KEY (capture_id, target_id),
        FOREIGN KEY (capture_id) REFERENCES captures(capture_id),
        FOREIGN KEY (response_sha256, source_byte_size)
            REFERENCES response_bodies(response_sha256, byte_size),
        FOREIGN KEY (index_response_sha256) REFERENCES response_bodies(response_sha256),
        FOREIGN KEY (selected_response_sha256) REFERENCES response_bodies(response_sha256),
        CHECK ((response_sha256 IS NULL) = (source_byte_size IS NULL)),
        CHECK ((selected_sha256 IS NULL) = (selected_byte_size IS NULL)),
        CHECK ((retrieval_mode = 'direct_url' AND sequence IS NULL) OR
            (retrieval_mode = 'bundle_sequence' AND sequence IS NOT NULL AND sequence > 0)),
        CHECK (response_sha256 IS NULL OR
            (length(response_sha256) = 64 AND response_sha256 NOT GLOB '*[^0-9a-f]*')),
        CHECK (selected_sha256 IS NULL OR
            (length(selected_sha256) = 64 AND selected_sha256 NOT GLOB '*[^0-9a-f]*')),
        CHECK (acquisition_status != 'not_filed' OR retrieval_mode = 'bundle_sequence' OR
            (optional = 1 AND catalog_direct_selection = 'exact_form_with_lazy_index' AND
             index_response_sha256 IS NOT NULL)),
        CHECK (acquisition_status != 'required_missing' OR
            (optional = 0 AND catalog_direct_selection = 'exact_form_with_lazy_index' AND
             index_response_sha256 IS NOT NULL)),
        CHECK (acquisition_status != 'acquired' OR
            (response_sha256 IS NOT NULL AND source_byte_size IS NOT NULL AND
             selected_sha256 IS NOT NULL AND selected_byte_size IS NOT NULL AND
             selected_filename IS NOT NULL)),
        CHECK (acquisition_status != 'acquired' OR retrieval_mode != 'direct_url' OR
            (response_sha256 = selected_sha256 AND source_byte_size = selected_byte_size))
    )""",
    """CREATE TRIGGER immutable_response_update BEFORE UPDATE ON response_bodies
        BEGIN SELECT RAISE(ABORT, 'fixture response bodies are immutable'); END""",
    """CREATE TRIGGER immutable_response_delete BEFORE DELETE ON response_bodies
        BEGIN SELECT RAISE(ABORT, 'fixture response bodies are immutable'); END""",
    """CREATE TRIGGER immutable_capture_update BEFORE UPDATE ON captures
        BEGIN SELECT RAISE(ABORT, 'fixture captures are immutable'); END""",
    """CREATE TRIGGER immutable_capture_delete BEFORE DELETE ON captures
        BEGIN SELECT RAISE(ABORT, 'fixture captures are immutable'); END""",
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
    connection.execute("PRAGMA user_version = 2")


def _validate_manifest(fixture: foundation_fixtures.FixturePaths) -> None:
    try:
        raw = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
        envelope = foundation_fixtures.FixtureManifestEnvelope.from_mapping(raw)
        if (
            envelope.fixture_kind != FIXTURE_KIND
            or envelope.fixture_id != fixture.fixture_id
            or envelope.storage_format != "sqlite"
            or envelope.storage_path != fixture.storage_filename
            or envelope.created_at != envelope.updated_at
            or envelope.details != {"store_schema_version": SCHEMA_VERSION}
        ):
            raise ValueError("fixture descriptor does not match the S9 store")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FixtureStoreError(
            f"invalid fixture manifest: {fixture.manifest_path}"
        ) from exc


def validate_database(connection: sqlite3.Connection, database: Path) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise FixtureStoreError("unsupported acquisition fixture schema version")
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


def open_fixture(
    paths: AcquisitionPaths, fixture_id: str, *, readonly: bool
) -> tuple[foundation_fixtures.FixturePaths, sqlite3.Connection]:
    fixture = fixture_paths(paths, fixture_id)
    if not fixture.manifest_path.is_file() or not fixture.storage_path.is_file():
        raise FixtureStoreError(f"fixture is missing or incomplete: {fixture.root}")
    _validate_manifest(fixture)
    connection = connect(fixture.storage_path, readonly=readonly)
    try:
        validate_database(connection, fixture.storage_path)
    except Exception:
        connection.close()
        raise
    return fixture, connection
