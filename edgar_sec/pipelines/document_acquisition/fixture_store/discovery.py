"""Read-only discovery of validated acquisition fixture metadata."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

from edgar_sec.foundation.runtime.paths import validate_path_component
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import open_fixture

_CASE_SELECT = """SELECT cases.capture_id, cases.target_id, cases.attempt_id,
    cases.accession, cases.form, cases.request_id, cases.target_role,
    cases.target_type, cases.optional, cases.catalog_direct_selection,
    cases.source_origin, cases.target_status, cases.retrieval_mode,
    cases.target_url, cases.final_url, cases.sequence, cases.acquisition_status,
    cases.error_code, cases.response_sha256, cases.index_response_sha256,
    cases.selected_response_sha256, cases.resolution_schema_version,
    cases.screen_kind, cases.screen_result, cases.evaluator_version,
    cases.index_parser_version, cases.matching_entry_ids_json,
    cases.selected_sequence, cases.selected_retrieval_mode, cases.selected_url,
    cases.source_byte_size, cases.selected_sha256, cases.selected_byte_size,
    cases.selected_filename, cases.content_type, cases.content_encoding,
    captures.run_id, captures.target_plan_id, captures.target_plan_digest,
    captures.target_plan_schema_version, captures.inventory_snapshot_id,
    captures.inventory_snapshot_digest, captures.captured_at_utc
FROM cases JOIN captures USING (capture_id)"""


@dataclass(frozen=True, slots=True)
class FixtureCaseMetadata:
    fixture_id: str
    capture_id: str
    target_id: str
    attempt_id: str
    accession: str
    form: str
    request_id: str
    target_role: str
    target_type: str
    optional: bool
    catalog_direct_selection: str | None
    source_origin: str
    target_status: str
    retrieval_mode: str
    target_url: str | None
    final_url: str | None
    sequence: int | None
    acquisition_status: str
    error_code: str | None
    response_sha256: str | None
    index_response_sha256: str | None
    selected_response_sha256: str | None
    resolution_schema_version: str | None
    screen_kind: str | None
    screen_result: str | None
    evaluator_version: str | None
    index_parser_version: str | None
    matching_entry_ids_json: str | None
    selected_sequence: int | None
    selected_retrieval_mode: str | None
    selected_url: str | None
    source_byte_size: int | None
    selected_sha256: str | None
    selected_byte_size: int | None
    selected_filename: str | None
    content_type: str | None
    content_encoding: str | None
    run_id: str
    target_plan_id: str
    target_plan_digest: str
    target_plan_schema_version: str
    inventory_snapshot_id: str | None
    inventory_snapshot_digest: str | None
    captured_at_utc: str


def _validated_fixture_id(fixture_id: str) -> str:
    return validate_path_component(fixture_id, "fixture_id")


def _check_fixture_root(paths: AcquisitionPaths, fixture_id: str) -> None:
    fixture = paths.fixture_paths(_validated_fixture_id(fixture_id))
    if fixture.root.is_symlink():
        raise FixtureStoreError(f"fixture root must not be a symlink: {fixture.root}")
    if fixture.manifest_path.is_symlink() or fixture.storage_path.is_symlink():
        raise FixtureStoreError(f"fixture files must not be symlinks: {fixture.root}")


def _fixture_ids(paths: AcquisitionPaths) -> Iterator[str]:
    root = paths.fixtures_root
    if root.is_symlink():
        raise FixtureStoreError(f"fixture registry must not be a symlink: {root}")
    if not root.exists():
        return
    if not root.is_dir():
        raise FixtureStoreError(f"fixture registry is not a directory: {root}")
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.is_symlink():
            raise FixtureStoreError(f"fixture root must not be a symlink: {entry}")
        if not entry.is_dir():
            continue
        fixture_id = _validated_fixture_id(entry.name)
        _check_fixture_root(paths, fixture_id)
        yield fixture_id


def iter_fixture_ids(paths: AcquisitionPaths) -> Iterator[str]:
    """Yield validated fixture IDs in deterministic order."""
    for fixture_id in _fixture_ids(paths):
        _, connection = open_fixture(paths, fixture_id, readonly=True)
        connection.close()
        yield fixture_id


def _metadata(fixture_id: str, row: tuple[object, ...]) -> FixtureCaseMetadata:
    return FixtureCaseMetadata(
        fixture_id=fixture_id,
        capture_id=row[0],
        target_id=row[1],
        attempt_id=row[2],
        accession=row[3],
        form=row[4],
        request_id=row[5],
        target_role=row[6],
        target_type=row[7],
        optional=bool(row[8]),
        catalog_direct_selection=row[9],
        source_origin=row[10],
        target_status=row[11],
        retrieval_mode=row[12],
        target_url=row[13],
        final_url=row[14],
        sequence=row[15],
        acquisition_status=row[16],
        error_code=row[17],
        response_sha256=row[18],
        index_response_sha256=row[19],
        selected_response_sha256=row[20],
        resolution_schema_version=row[21],
        screen_kind=row[22],
        screen_result=row[23],
        evaluator_version=row[24],
        index_parser_version=row[25],
        matching_entry_ids_json=row[26],
        selected_sequence=row[27],
        selected_retrieval_mode=row[28],
        selected_url=row[29],
        source_byte_size=row[30],
        selected_sha256=row[31],
        selected_byte_size=row[32],
        selected_filename=row[33],
        content_type=row[34],
        content_encoding=row[35],
        run_id=row[36],
        target_plan_id=row[37],
        target_plan_digest=row[38],
        target_plan_schema_version=row[39],
        inventory_snapshot_id=row[40],
        inventory_snapshot_digest=row[41],
        captured_at_utc=row[42],
    )


def _fixture_case_rows(
    paths: AcquisitionPaths,
    fixture_id: str,
    capture_id: str | None,
    target_id: str | None,
) -> Iterator[FixtureCaseMetadata]:
    _check_fixture_root(paths, fixture_id)
    _, connection = open_fixture(paths, fixture_id, readonly=True)
    clauses: list[str] = []
    parameters: list[str] = []
    if capture_id is not None:
        clauses.append("cases.capture_id = ?")
        parameters.append(capture_id)
    if target_id is not None:
        clauses.append("cases.target_id = ?")
        parameters.append(target_id)
    query = _CASE_SELECT
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY cases.capture_id, cases.target_id"
    try:
        cursor = connection.execute(query, parameters)
        try:
            for row in cursor:
                yield _metadata(fixture_id, row)
        finally:
            cursor.close()
    finally:
        connection.close()


def iter_fixture_cases(
    paths: AcquisitionPaths,
    *,
    fixture_id: str | None = None,
    capture_id: str | None = None,
    target_id: str | None = None,
) -> Iterator[FixtureCaseMetadata]:
    """Stream validated fixture cases with optional exact-value filters."""
    if fixture_id is not None:
        yield from _fixture_case_rows(
            paths, _validated_fixture_id(fixture_id), capture_id, target_id
        )
        return
    for discovered_id in _fixture_ids(paths):
        yield from _fixture_case_rows(paths, discovered_id, capture_id, target_id)


def get_fixture_case(
    paths: AcquisitionPaths, fixture_id: str, capture_id: str, target_id: str
) -> FixtureCaseMetadata:
    """Return one exact fixture case or raise when it does not exist."""
    _check_fixture_root(paths, fixture_id)
    _, connection = open_fixture(paths, fixture_id, readonly=True)
    try:
        row = connection.execute(
            _CASE_SELECT + " WHERE cases.capture_id = ? AND cases.target_id = ?",
            (capture_id, target_id),
        ).fetchone()
        if row is None:
            raise FixtureStoreError("fixture case not found")
        return _metadata(fixture_id, row)
    finally:
        connection.close()


__all__ = [
    "FixtureCaseMetadata",
    "get_fixture_case",
    "iter_fixture_cases",
    "iter_fixture_ids",
]
