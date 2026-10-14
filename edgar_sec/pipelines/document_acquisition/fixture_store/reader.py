from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.pipelines.document_acquisition.fixture_store.body_verification import (
    _write_verified_body,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureCaseMetadata,
    FixtureSummary,
    get_fixture_case,
    iter_fixture_cases,
    list_fixture_summaries as _list_fixture_summaries,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureOperationError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import open_fixture
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths


@dataclass(frozen=True, slots=True)
class FixtureMaterializationResult:
    fixture_id: str
    capture_id: str
    target_id: str
    body_sha256: str
    byte_size: int
    output_path: Path


@dataclass(frozen=True, slots=True)
class FixtureLazyIndex:
    accession: str
    index_url: str
    body_sha256: str
    byte_size: int
    body: bytes


@dataclass(frozen=True, slots=True)
class FixtureLazyIndexMetadata:
    accession: str
    index_url: str
    body_sha256: str
    byte_size: int


def list_fixture_summaries(paths: AcquisitionPaths) -> Iterator[FixtureSummary]:
    return iter(_list_fixture_summaries(paths))


def list_fixture_cases(
    paths: AcquisitionPaths, *, fixture_id: str | None = None
) -> Iterator[FixtureCaseMetadata]:
    return iter_fixture_cases(paths, fixture_id=fixture_id)


def read_fixture_lazy_index(
    paths: AcquisitionPaths, fixture_id: str, accession: str
) -> FixtureLazyIndex | None:
    _, connection = open_fixture(paths, fixture_id, readonly=True)
    try:
        row = connection.execute(
            "SELECT index_url, body_sha256, byte_size FROM lazy_indexes "
            "WHERE accession = ?",
            (accession,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    with tempfile.TemporaryFile(mode="w+b") as stream:
        _write_verified_body(paths, fixture_id, row[1], stream)
        stream.seek(0)
        body = stream.read()
    if len(body) != row[2]:
        raise FixtureOperationError("cached lazy-index size differs from its record")
    return FixtureLazyIndex(accession, row[0], row[1], row[2], body)


def count_fixture_lazy_indexes(paths: AcquisitionPaths, fixture_id: str) -> int:
    _, connection = open_fixture(paths, fixture_id, readonly=True)
    try:
        return int(
            connection.execute("SELECT COUNT(*) FROM lazy_indexes").fetchone()[0]
        )
    finally:
        connection.close()


def verify_fixture_lazy_index(
    paths: AcquisitionPaths,
    fixture_id: str,
    accession: str,
    expected_sha256: str,
) -> FixtureLazyIndexMetadata:
    _, connection = open_fixture(paths, fixture_id, readonly=True)
    try:
        row = connection.execute(
            "SELECT index_url, body_sha256, byte_size FROM lazy_indexes "
            "WHERE accession = ?",
            (accession,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or row[1] != expected_sha256:
        raise FixtureOperationError(
            "fixture lazy-index reference is missing or changed"
        )
    with tempfile.TemporaryFile(mode="w+b") as stream:
        _write_verified_body(paths, fixture_id, row[1], stream)
    return FixtureLazyIndexMetadata(accession, row[0], row[1], row[2])


def _materialization_destination(paths: AcquisitionPaths, output_path: Path) -> Path:
    output = Path(output_path).expanduser()
    if output.is_symlink():
        raise FixtureOperationError("materialized body must not be a symlink")
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise FixtureOperationError("materialization parent is not a directory")
    destination = parent / output.name
    if destination.exists() or destination.is_symlink():
        raise FixtureOperationError("materialized body already exists")
    for root in (
        paths.fixtures_root,
        paths.runs_root,
        paths.snapshots_root,
        paths.review_runs_root,
    ):
        if destination.is_relative_to(root.resolve()):
            raise FixtureOperationError(
                "materialized body cannot be inside managed artifacts"
            )
    return destination


def _materialize_fixture_case(
    fixture_id: str,
    capture_id: str,
    target_id: str,
    output_path: Path,
    *,
    paths: AcquisitionPaths,
) -> FixtureMaterializationResult:
    case = get_fixture_case(paths, fixture_id, capture_id, target_id)
    destination = _materialization_destination(paths, output_path)
    with tempfile.TemporaryDirectory(
        prefix="fixture-body-", dir=destination.parent
    ) as temporary:
        staged_path = Path(temporary) / "body.bin"
        with staged_path.open("xb") as stream:
            body = _write_verified_body(paths, fixture_id, case.body_sha256, stream)
        if body.byte_size != case.byte_size:
            raise FixtureOperationError(
                "materialized body size differs from case identity"
            )
        try:
            os.link(staged_path, destination)
        except FileExistsError as error:
            raise FixtureOperationError("materialized body already exists") from error
    return FixtureMaterializationResult(
        fixture_id,
        capture_id,
        target_id,
        case.body_sha256,
        case.byte_size,
        destination,
    )
