"""Fixture creation and atomic append of compressed acquisition evidence."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import BinaryIO

import zstandard

import edgar_sec.foundation.runtime.fixtures as foundation_fixtures
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
    ResponseBodyRef,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.replay import (
    verify_response_row,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    CHUNK_SIZE,
    FIXTURE_KIND,
    SCHEMA_VERSION,
    _CASE_COLUMNS,
    _CAPTURE_COLUMNS,
    connect,
    create_schema,
    fixture_paths,
    open_fixture,
)

_INSERT_CAPTURE_SQL = """INSERT INTO captures (
    capture_id, run_id, target_plan_id, target_plan_digest,
    target_plan_schema_version, inventory_snapshot_id,
    inventory_snapshot_digest, captured_at_utc
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
_SELECT_CAPTURE_SQL = """SELECT capture_id, run_id, target_plan_id,
    target_plan_digest, target_plan_schema_version, inventory_snapshot_id,
    inventory_snapshot_digest, captured_at_utc
FROM captures WHERE capture_id = ?"""
_INSERT_CASE_SQL = """INSERT INTO cases (
    capture_id, target_id, attempt_id, accession, form, request_id, target_role,
    target_type, optional, catalog_direct_selection, source_origin, target_status,
    retrieval_mode, target_url, final_url, sequence, acquisition_status, error_code,
    response_sha256, index_response_sha256, selected_response_sha256,
    resolution_schema_version, screen_kind, screen_result, evaluator_version,
    index_parser_version, matching_entry_ids_json, selected_sequence,
    selected_retrieval_mode, selected_url, source_byte_size, selected_sha256,
    selected_byte_size, selected_filename, content_type, content_encoding
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
_SELECT_CASE_SQL = """SELECT capture_id, target_id, attempt_id, accession, form,
    request_id, target_role, target_type, optional, catalog_direct_selection,
    source_origin, target_status, retrieval_mode, target_url, final_url, sequence,
    acquisition_status, error_code, response_sha256, index_response_sha256,
    selected_response_sha256, resolution_schema_version, screen_kind,
    screen_result, evaluator_version, index_parser_version,
    matching_entry_ids_json, selected_sequence, selected_retrieval_mode,
    selected_url, source_byte_size, selected_sha256, selected_byte_size,
    selected_filename, content_type, content_encoding
FROM cases WHERE capture_id = ? AND target_id = ?"""


def initialize_fixture(
    paths: AcquisitionPaths, fixture_id: str
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
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        envelope = foundation_fixtures.FixtureManifestEnvelope(
            fixture_kind=FIXTURE_KIND,
            fixture_id=fixture_id,
            storage_format="sqlite",
            storage_path=fixture.storage_filename,
            created_at=created_at,
            updated_at=created_at,
            details={"store_schema_version": SCHEMA_VERSION},
        )
        atomic_write_json(fixture.manifest_path, envelope.to_mapping(), indent=2)
    except Exception:
        connection.close()
        raise
    connection.close()
    return fixture


def _stage_response(
    source: BinaryIO, max_response_bytes: int
) -> tuple[BinaryIO, str, int, str, int]:
    if max_response_bytes < 0:
        raise ValueError("max_response_bytes must be non-negative")
    staged = tempfile.TemporaryFile(mode="w+b")
    response_digest = hashlib.sha256()
    response_size = 0
    compressor = zstandard.ZstdCompressor()
    try:
        with compressor.stream_writer(
            staged, closefd=False, write_size=CHUNK_SIZE
        ) as writer:
            while chunk := source.read(CHUNK_SIZE):
                if not isinstance(chunk, bytes):
                    raise TypeError("response source must yield bytes")
                response_size += len(chunk)
                if response_size > max_response_bytes:
                    raise FixtureStoreError("response exceeds max_response_bytes")
                response_digest.update(chunk)
                writer.write(chunk)
        staged.flush()
        stored_size = staged.tell()
        staged.seek(0)
        stored_digest = hashlib.sha256()
        while chunk := staged.read(CHUNK_SIZE):
            stored_digest.update(chunk)
        staged.seek(0)
        return (
            staged,
            response_digest.hexdigest(),
            response_size,
            stored_digest.hexdigest(),
            stored_size,
        )
    except Exception:
        staged.close()
        raise


def _add_body(
    connection: sqlite3.Connection,
    staged: BinaryIO,
    response_sha256: str,
    byte_size: int,
    stored_sha256: str,
    stored_byte_size: int,
) -> tuple[bool, str, int]:
    existing = connection.execute(
        "SELECT body_id, response_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size "
        "FROM response_bodies WHERE response_sha256 = ?",
        (response_sha256,),
    ).fetchone()
    if existing is not None:
        if existing[2] != byte_size:
            raise FixtureStoreError("response digest exists with conflicting byte size")
        verify_response_row(connection, existing)
        return True, existing[4], existing[5]
    blob_limit = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    if stored_byte_size > blob_limit:
        raise FixtureStoreError("compressed response exceeds SQLite BLOB limit")
    cursor = connection.execute(
        "INSERT INTO response_bodies "
        "(response_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size, compressed_body) "
        "VALUES (?, ?, 'zstd', ?, ?, zeroblob(?))",
        (response_sha256, byte_size, stored_sha256, stored_byte_size, stored_byte_size),
    )
    staged.seek(0)
    blob = connection.blobopen(
        "response_bodies", "compressed_body", cursor.lastrowid, readonly=False
    )
    try:
        while chunk := staged.read(CHUNK_SIZE):
            blob.write(chunk)
        if blob.tell() != stored_byte_size:
            raise FixtureStoreError("compressed staging size changed during insertion")
    finally:
        blob.close()
    row = connection.execute(
        "SELECT body_id, response_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size "
        "FROM response_bodies WHERE body_id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    verify_response_row(connection, row)
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
        select_sql = _SELECT_CAPTURE_SQL
        insert_sql = _INSERT_CAPTURE_SQL
        key_values = (values["capture_id"],)
    elif table == "cases":
        select_sql = _SELECT_CASE_SQL
        insert_sql = _INSERT_CASE_SQL
        key_values = (values["capture_id"], values["target_id"])
    else:
        raise FixtureStoreError(f"unsupported immutable table: {table}")
    prior = connection.execute(select_sql, key_values).fetchone()
    if prior is not None:
        expected = tuple(values.get(column) for column in columns)
        if prior != expected:
            raise FixtureStoreError(f"conflicting immutable {table} record")
        return False
    if set(values) != set(columns):
        missing = set(columns) - set(values)
        raise FixtureStoreError(f"missing {table} fields: {sorted(missing)}")
    connection.execute(insert_sql, tuple(values[column] for column in columns))
    return True


def append_fixture_case(
    paths: AcquisitionPaths,
    fixture_id: str,
    capture: Mapping[str, object],
    case: Mapping[str, object],
    source: BinaryIO | None,
    *,
    max_response_bytes: int,
    related_responses: Mapping[str, BinaryIO] | None = None,
) -> ResponseBodyRef | None:
    """Append one immutable case, optionally retaining its exact source response."""
    case_values = dict(case)
    staged_responses: dict[str, tuple[BinaryIO, str, int, str, int]] = {}
    if source is None and (
        case_values.get("response_sha256") is not None
        or case_values.get("source_byte_size") is not None
    ):
        raise FixtureStoreError("case response identity requires a source stream")
    try:
        if source is not None:
            body_info = _stage_response(source, max_response_bytes)
            if case_values.get("response_sha256") not in (None, body_info[1]):
                body_info[0].close()
                raise FixtureStoreError(
                    "response_sha256 does not match its source stream"
                )
            if case_values.get("source_byte_size") not in (None, body_info[2]):
                body_info[0].close()
                raise FixtureStoreError(
                    "source_byte_size does not match its source stream"
                )
            staged_responses["response_sha256"] = body_info
        for field, response_stream in (related_responses or {}).items():
            if field not in {"index_response_sha256", "selected_response_sha256"}:
                raise FixtureStoreError(f"unsupported related response field: {field}")
            expected_digest = case_values.get(field)
            if not isinstance(expected_digest, str):
                raise FixtureStoreError(f"{field} must identify its response stream")
            staged_responses[field] = _stage_response(
                response_stream, max_response_bytes
            )
            if staged_responses[field][1] != expected_digest:
                raise FixtureStoreError(f"{field} does not match its response stream")
        _, connection = open_fixture(paths, fixture_id, readonly=False)
        try:
            with connection:
                body_ref = None
                stored_refs: dict[str, ResponseBodyRef] = {}
                for field, body_info in staged_responses.items():
                    (
                        staged,
                        response_digest,
                        response_size,
                        stored_digest,
                        stored_size,
                    ) = body_info
                    limit = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
                    if stored_size > limit:
                        raise FixtureStoreError(
                            "compressed response exceeds SQLite BLOB limit"
                        )
                    reused, actual_stored_digest, actual_stored_size = _add_body(
                        connection,
                        staged,
                        response_digest,
                        response_size,
                        stored_digest,
                        stored_size,
                    )
                    stored_ref = ResponseBodyRef(
                        response_digest,
                        response_size,
                        actual_stored_digest,
                        actual_stored_size,
                        reused,
                    )
                    stored_refs[field] = stored_ref
                    if field == "response_sha256":
                        body_ref = stored_ref
                if body_ref is not None:
                    case_values["response_sha256"] = body_ref.response_sha256
                    case_values["source_byte_size"] = body_ref.byte_size
                    if (
                        case_values.get("acquisition_status") == "acquired"
                        and case_values.get("retrieval_mode") == "direct_url"
                    ):
                        if case_values.get("selected_sha256") is None:
                            case_values["selected_sha256"] = body_ref.response_sha256
                        if case_values.get("selected_byte_size") is None:
                            case_values["selected_byte_size"] = body_ref.byte_size
                elif source is None:
                    case_values["response_sha256"] = None
                    case_values["source_byte_size"] = None
                for field, body in stored_refs.items():
                    if field != "response_sha256":
                        case_values[field] = body.response_sha256
                for field in (
                    "response_sha256",
                    "index_response_sha256",
                    "selected_response_sha256",
                ):
                    digest = case_values.get(field)
                    if digest is not None:
                        row = connection.execute(
                            "SELECT body_id, response_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size "
                            "FROM response_bodies WHERE response_sha256 = ?",
                            (digest,),
                        ).fetchone()
                        if row is None:
                            raise FixtureStoreError(
                                "referenced fixture response body is missing"
                            )
                        verify_response_row(connection, row)
                capture_values = dict(capture)
                _insert_immutable(
                    connection,
                    "captures",
                    _CAPTURE_COLUMNS,
                    capture_values,
                )
                case_values["capture_id"] = capture_values.get("capture_id")
                _insert_immutable(
                    connection,
                    "cases",
                    _CASE_COLUMNS,
                    case_values,
                )
        finally:
            connection.close()
        return body_ref
    except sqlite3.Error as exc:
        raise FixtureStoreError("failed to append acquisition fixture case") from exc
    finally:
        for staged, *_ in staged_responses.values():
            staged.close()
