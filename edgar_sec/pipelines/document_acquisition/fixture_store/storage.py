"""Fixture creation and atomic append of compressed parser bodies."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import BinaryIO

import zstandard

import edgar_sec.foundation.runtime.fixtures as foundation_fixtures
from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_acquisition.fixture_store.body_verification import (
    _verify_body_row,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureBodyRef,
    FixturePlanPin,
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    FIXTURE_KIND,
    SCHEMA_VERSION,
    _CAPTURE_COLUMNS,
    _CASE_COLUMNS,
    connect,
    create_schema,
    fixture_paths,
    open_fixture,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths

_INSERT_CAPTURE_SQL = """INSERT INTO captures (
    capture_id, run_id, target_plan_id, target_plan_digest,
    target_plan_schema_version, captured_at_utc
) VALUES (?, ?, ?, ?, ?, ?)"""
_SELECT_CAPTURE_SQL = """SELECT capture_id, run_id, target_plan_id,
    target_plan_digest, target_plan_schema_version, captured_at_utc
FROM captures WHERE capture_id = ?"""
_INSERT_CASE_SQL = """INSERT INTO cases (
    capture_id, target_id, attempt_id, accession, form, request_id, target_role,
    target_type, source_origin, retrieval_mode, target_url, sequence,
    selected_filename, body_sha256, byte_size
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
_SELECT_CASE_SQL = """SELECT capture_id, target_id, attempt_id, accession, form,
    request_id, target_role, target_type, source_origin, retrieval_mode,
    target_url, sequence, selected_filename, body_sha256, byte_size
FROM cases WHERE capture_id = ? AND target_id = ?"""


def initialize_fixture(
    paths: AcquisitionPaths, fixture_id: str, plan_pin: FixturePlanPin
) -> foundation_fixtures.FixturePaths:
    fixture = fixture_paths(paths, fixture_id)
    if fixture.root.exists():
        raise FixtureStoreError(
            f"fixture already exists or is incomplete: {fixture.root}"
        )
    fixture.root.mkdir(parents=True)
    connection = connect(fixture.storage_path)
    try:
        with connection:
            create_schema(connection)
            connection.executemany(
                "INSERT INTO fixture_meta (key, value) VALUES (?, ?)",
                (
                    ("target_plan_id", plan_pin.target_plan_id),
                    ("target_plan_digest", plan_pin.target_plan_digest),
                    (
                        "target_plan_schema_version",
                        str(plan_pin.target_plan_schema_version),
                    ),
                ),
            )
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        envelope = foundation_fixtures.FixtureManifestEnvelope(
            fixture_kind=FIXTURE_KIND,
            fixture_id=fixture_id,
            storage_format="sqlite",
            storage_path=fixture.storage_filename,
            created_at=created_at,
            updated_at=created_at,
            details={
                "store_schema_version": SCHEMA_VERSION,
                "target_plan_id": plan_pin.target_plan_id,
                "target_plan_digest": plan_pin.target_plan_digest,
                "target_plan_schema_version": plan_pin.target_plan_schema_version,
            },
        )
        atomic_write_json(fixture.manifest_path, envelope.to_mapping(), indent=2)
    except Exception:
        connection.close()
        raise
    connection.close()
    return fixture


def _stage_body(
    source: BinaryIO, max_body_bytes: int
) -> tuple[BinaryIO, str, int, str, int]:
    if max_body_bytes < 0:
        raise ValueError("max_body_bytes must be non-negative")
    staged = tempfile.TemporaryFile(mode="w+b")
    body_digest = hashlib.sha256()
    body_size = 0
    compressor = zstandard.ZstdCompressor()
    try:
        with compressor.stream_writer(
            staged, closefd=False, write_size=DEFAULT_IO_CHUNK_SIZE
        ) as writer:
            while chunk := source.read(DEFAULT_IO_CHUNK_SIZE):
                if not isinstance(chunk, bytes):
                    raise TypeError("body source must yield bytes")
                body_size += len(chunk)
                if body_size > max_body_bytes:
                    raise FixtureStoreError("parser body exceeds max_body_bytes")
                body_digest.update(chunk)
                writer.write(chunk)
        staged.flush()
        stored_size = staged.tell()
        staged.seek(0)
        stored_digest = hashlib.sha256()
        while chunk := staged.read(DEFAULT_IO_CHUNK_SIZE):
            stored_digest.update(chunk)
        staged.seek(0)
        return (
            staged,
            body_digest.hexdigest(),
            body_size,
            stored_digest.hexdigest(),
            stored_size,
        )
    except Exception:
        staged.close()
        raise


def _add_body(
    connection: sqlite3.Connection,
    staged: BinaryIO,
    body_sha256: str,
    byte_size: int,
    stored_sha256: str,
    stored_byte_size: int,
) -> tuple[bool, str, int]:
    existing = connection.execute(
        "SELECT body_id, body_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size "
        "FROM body_blobs WHERE body_sha256 = ?",
        (body_sha256,),
    ).fetchone()
    if existing is not None:
        if existing[2] != byte_size:
            raise FixtureStoreError("body digest exists with conflicting byte size")
        _verify_body_row(connection, existing)
        return True, existing[4], existing[5]
    if stored_byte_size > connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH):
        raise FixtureStoreError("compressed body exceeds SQLite BLOB limit")
    cursor = connection.execute(
        "INSERT INTO body_blobs "
        "(body_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size, compressed_body) "
        "VALUES (?, ?, 'zstd', ?, ?, zeroblob(?))",
        (body_sha256, byte_size, stored_sha256, stored_byte_size, stored_byte_size),
    )
    staged.seek(0)
    blob = connection.blobopen(
        "body_blobs", "compressed_body", cursor.lastrowid, readonly=False
    )
    try:
        while chunk := staged.read(DEFAULT_IO_CHUNK_SIZE):
            blob.write(chunk)
        if blob.tell() != stored_byte_size:
            raise FixtureStoreError("compressed staging size changed during insertion")
    finally:
        blob.close()
    row = connection.execute(
        "SELECT body_id, body_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size "
        "FROM body_blobs WHERE body_id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    _verify_body_row(connection, row)
    return False, stored_sha256, stored_byte_size


def _insert_immutable(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    values: Mapping[str, object],
) -> bool:
    unknown = set(values) - set(columns)
    if unknown:
        raise FixtureStoreError(f"unknown {table} fields: {sorted(unknown)}")
    if table == "captures":
        select_sql, insert_sql = _SELECT_CAPTURE_SQL, _INSERT_CAPTURE_SQL
        key = (values["capture_id"],)
    elif table == "cases":
        select_sql, insert_sql = _SELECT_CASE_SQL, _INSERT_CASE_SQL
        key = (values["capture_id"], values["target_id"])
    else:
        raise FixtureStoreError(f"unsupported immutable table: {table}")
    prior = connection.execute(select_sql, key).fetchone()
    if prior is not None:
        if prior != tuple(values.get(column) for column in columns):
            raise FixtureStoreError(f"conflicting immutable {table} record")
        return False
    if set(values) != set(columns):
        raise FixtureStoreError(
            f"missing {table} fields: {sorted(set(columns) - set(values))}"
        )
    connection.execute(insert_sql, tuple(values[column] for column in columns))
    return True


def append_fixture_case(
    paths: AcquisitionPaths,
    fixture_id: str,
    capture: Mapping[str, object],
    case: Mapping[str, object],
    source: BinaryIO,
    *,
    max_body_bytes: int,
) -> FixtureBodyRef:
    staged, body_sha256, byte_size, stored_sha256, stored_byte_size = _stage_body(
        source, max_body_bytes
    )
    try:
        case_values = dict(case)
        if (case_values.get("body_sha256"), case_values.get("byte_size")) != (
            body_sha256,
            byte_size,
        ):
            raise FixtureStoreError("body identity does not match its source stream")
        _, connection = open_fixture(paths, fixture_id, readonly=False)
        try:
            with connection:
                pin = dict(connection.execute("SELECT key, value FROM fixture_meta"))
                if (
                    capture.get("target_plan_id") != pin["target_plan_id"]
                    or capture.get("target_plan_digest") != pin["target_plan_digest"]
                    or str(capture.get("target_plan_schema_version"))
                    != pin["target_plan_schema_version"]
                ):
                    raise FixtureStoreError("capture run differs from fixture plan pin")
                reused, actual_stored_sha256, actual_stored_size = _add_body(
                    connection,
                    staged,
                    body_sha256,
                    byte_size,
                    stored_sha256,
                    stored_byte_size,
                )
                _insert_immutable(
                    connection, "captures", _CAPTURE_COLUMNS, dict(capture)
                )
                _insert_immutable(connection, "cases", _CASE_COLUMNS, case_values)
            return FixtureBodyRef(
                body_sha256,
                byte_size,
                actual_stored_sha256,
                actual_stored_size,
                reused,
            )
        finally:
            connection.close()
    finally:
        staged.close()
