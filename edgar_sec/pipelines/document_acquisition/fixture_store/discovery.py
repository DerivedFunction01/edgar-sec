from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.runtime.paths import validate_path_component
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    fixture_paths,
    open_fixture,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths

_CASE_SELECT = """SELECT cases.capture_id, cases.target_id,
    cases.inventory_entry_id, cases.selection_source, cases.index_sha256,
    cases.accession, cases.form, cases.request_id, cases.target_role,
    cases.target_type, cases.source_origin, cases.retrieval_mode,
    cases.target_url, cases.sequence, cases.selected_filename,
    cases.body_sha256, cases.byte_size, cases.filing_date, cases.report_date,
    captures.target_plan_id, captures.target_plan_digest,
    captures.target_plan_schema_version, captures.captured_at_utc
FROM cases JOIN captures USING (capture_id)"""


@dataclass(frozen=True, slots=True)
class FixtureCaseMetadata:
    fixture_id: str
    capture_id: str
    target_id: str
    inventory_entry_id: str | None
    selection_source: str
    index_sha256: str | None
    accession: str
    form: str
    request_id: str
    target_role: str
    target_type: str
    source_origin: str
    retrieval_mode: str
    target_url: str | None
    sequence: int | None
    selected_filename: str
    body_sha256: str
    byte_size: int
    filing_date: str | None
    report_date: str | None
    target_plan_id: str
    target_plan_digest: str
    target_plan_schema_version: int
    captured_at_utc: str


@dataclass(frozen=True, slots=True)
class FixtureSummary:
    fixture_id: str
    target_plan_id: str
    target_plan_digest: str
    target_plan_schema_version: int
    capture_count: int
    case_count: int
    lazy_index_count: int


def _validated_fixture_id(fixture_id: str) -> str:
    return validate_path_component(fixture_id, "fixture_id")


def _check_fixture_root(paths: AcquisitionPaths, fixture_id: str) -> None:
    fixture = fixture_paths(paths, _validated_fixture_id(fixture_id))
    if fixture.root.is_symlink():
        raise FixtureStoreError(f"fixture root must not be a symlink: {fixture.root}")
    if fixture.manifest_path.is_symlink() or fixture.storage_path.is_symlink():
        raise FixtureStoreError("fixture files must not be symlinks")


def _fixture_ids(paths: AcquisitionPaths) -> tuple[str, ...]:
    root = paths.fixtures_root
    if not root.exists():
        return ()
    if root.is_symlink() or not root.is_dir():
        raise FixtureStoreError(f"fixture root is unsafe: {root}")
    ids = []
    for item in sorted(root.iterdir(), key=lambda path: path.name):
        if not item.is_dir() or item.is_symlink():
            continue
        try:
            fixture_id = _validated_fixture_id(item.name)
            _check_fixture_root(paths, fixture_id)
            _, connection = open_fixture(paths, fixture_id, readonly=True)
            connection.close()
        except (FixtureStoreError, OSError, ValueError):
            continue
        ids.append(fixture_id)
    return tuple(ids)


def _case_from_row(fixture_id: str, row: tuple[object, ...]) -> FixtureCaseMetadata:
    if not is_sha256_hex_digest(row[15]):
        raise FixtureStoreError("fixture body digest is invalid")
    if row[4] is not None and not is_sha256_hex_digest(row[4]):
        raise FixtureStoreError("fixture lazy-index digest is invalid")
    return FixtureCaseMetadata(
        fixture_id=fixture_id,
        capture_id=row[0],
        target_id=row[1],
        inventory_entry_id=row[2],
        selection_source=row[3],
        index_sha256=row[4],
        accession=row[5],
        form=row[6],
        request_id=row[7],
        target_role=row[8],
        target_type=row[9],
        source_origin=row[10],
        retrieval_mode=row[11],
        target_url=row[12],
        sequence=row[13],
        selected_filename=row[14],
        body_sha256=row[15],
        byte_size=row[16],
        filing_date=row[17],
        report_date=row[18],
        target_plan_id=row[19],
        target_plan_digest=row[20],
        target_plan_schema_version=int(row[21]),
        captured_at_utc=row[22],
    )


def _fixture_case_rows(
    paths: AcquisitionPaths, fixture_id: str
) -> Iterator[FixtureCaseMetadata]:
    _check_fixture_root(paths, fixture_id)
    _, connection = open_fixture(paths, fixture_id, readonly=True)
    try:
        for row in connection.execute(
            _CASE_SELECT + " ORDER BY cases.capture_id, cases.target_id"
        ):
            yield _case_from_row(fixture_id, row)
    except sqlite3.Error as error:
        raise FixtureStoreError(f"cannot read fixture cases: {fixture_id}") from error
    finally:
        connection.close()


def iter_fixture_cases(
    paths: AcquisitionPaths, *, fixture_id: str | None = None
) -> Iterator[FixtureCaseMetadata]:
    """Stream fixture cases in deterministic order."""
    if fixture_id is not None:
        yield from _fixture_case_rows(paths, _validated_fixture_id(fixture_id))
        return
    for discovered_id in _fixture_ids(paths):
        yield from _fixture_case_rows(paths, discovered_id)


def list_fixture_summaries(paths: AcquisitionPaths) -> tuple[FixtureSummary, ...]:
    summaries = []
    for fixture_id in _fixture_ids(paths):
        fixture, connection = open_fixture(paths, fixture_id, readonly=True)
        try:
            manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
            target_plan_version = int(manifest["details"]["target_plan_schema_version"])
            meta = dict(connection.execute("SELECT key, value FROM fixture_meta"))
            capture_count = connection.execute(
                "SELECT COUNT(*) FROM captures"
            ).fetchone()[0]
            case_count = connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            lazy_index_count = connection.execute(
                "SELECT COUNT(*) FROM lazy_indexes"
            ).fetchone()[0]
            summaries.append(
                FixtureSummary(
                    fixture_id,
                    meta["target_plan_id"],
                    meta["target_plan_digest"],
                    target_plan_version,
                    capture_count,
                    case_count,
                    lazy_index_count,
                )
            )
        except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as error:
            raise FixtureStoreError(
                f"cannot summarize fixture: {fixture_id}"
            ) from error
        finally:
            connection.close()
    return tuple(summaries)


def get_fixture_case(
    paths: AcquisitionPaths,
    fixture_id: str,
    capture_id: str,
    target_id: str,
) -> FixtureCaseMetadata:
    _check_fixture_root(paths, fixture_id)
    _, connection = open_fixture(paths, fixture_id, readonly=True)
    try:
        row = connection.execute(
            _CASE_SELECT + " WHERE cases.capture_id = ? AND cases.target_id = ?",
            (capture_id, target_id),
        ).fetchone()
    except sqlite3.Error as error:
        raise FixtureStoreError(f"cannot read fixture case: {fixture_id}") from error
    finally:
        connection.close()
    if row is None:
        raise FixtureStoreError("fixture case not found")
    return _case_from_row(fixture_id, row)
