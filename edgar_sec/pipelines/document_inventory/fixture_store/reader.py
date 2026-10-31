"""Read fixture metadata and replay exact captured response bytes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import zstandard as zstd

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.compression import decompress_payload
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.pipelines.document_inventory.fixture_store._db import (
    count_rows,
    distinct_accession_count,
    load_manifest,
    open_readonly,
    validate_database,
)
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    CapturedIndexCase,
    CapturedIndexPage,
    FixtureListStatus,
    IndexFixtureError,
    IndexResponseKey,
)
from edgar_sec.foundation.runtime.fixtures import FixturePaths


class IndexFixtureReader:
    """Read-only context for a fixture's case index and compressed pages."""

    def __init__(self, paths: FixturePaths) -> None:
        self.paths = paths
        self._connection: sqlite3.Connection | None = None
        self.fixture_id: str | None = None

    def __enter__(self) -> IndexFixtureReader:
        if not self.paths.manifest_path.is_file():
            raise IndexFixtureError(
                f"fixture manifest missing: {self.paths.manifest_path}"
            )
        if not self.paths.storage_path.is_file():
            raise IndexFixtureError(
                f"fixture database missing: {self.paths.storage_path}"
            )
        manifest = load_manifest(self.paths)
        self.fixture_id = manifest.fixture_id
        connection = open_readonly(self.paths.storage_path)
        try:
            validate_database(
                connection, self.paths.storage_path, manifest.schema_version
            )
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def iter_cases(
        self,
        accession: AccessionNumber | str | None = None,
        *,
        batch_size: int = 128,
    ) -> Iterator[CapturedIndexCase]:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        connection = self._require_connection()
        cursor = connection.cursor()
        query = """
            SELECT DISTINCT accession, request_url, response_sha256
            FROM index_cases
        """
        parameters: tuple[str, ...] = ()
        if accession is not None:
            query += " WHERE accession = ?"
            value = (
                str(accession) if isinstance(accession, AccessionNumber) else accession
            )
            parameters = (value,)
        query += " ORDER BY accession, request_url, response_sha256"
        try:
            cursor.execute(query, parameters)
            while rows := cursor.fetchmany(batch_size):
                for acc, url, digest in rows:
                    yield CapturedIndexCase(
                        accession=AccessionNumber(str(acc)),
                        key=IndexResponseKey(str(url), str(digest)),
                    )
        finally:
            cursor.close()

    def list_cases(
        self, accession: AccessionNumber | str | None = None
    ) -> tuple[CapturedIndexCase, ...]:
        """Return cases for one small accession; use ``iter_cases`` for a fixture."""
        if accession is None:
            raise ValueError("list_cases requires an accession; use iter_cases for all")
        return tuple(self.iter_cases(accession))

    def count_cases(self, accession: AccessionNumber | str | None = None) -> int:
        connection = self._require_connection()
        query = "SELECT COUNT(*) FROM (SELECT DISTINCT accession, request_url, response_sha256 FROM index_cases"
        parameters: tuple[str, ...] = ()
        if accession is not None:
            value = (
                str(accession) if isinstance(accession, AccessionNumber) else accession
            )
            query += " WHERE accession = ?"
            parameters = (value,)
        query += ")"
        return int(connection.execute(query, parameters).fetchone()[0])

    def replay(
        self, accession: AccessionNumber | str, key: IndexResponseKey
    ) -> CapturedIndexPage:
        connection = self._require_connection()
        accession_text = str(accession)
        row = connection.execute(
            """
            SELECT r.request_url, r.response_sha256, r.compressed_body, r.captured_at
            FROM index_cases c
            JOIN index_responses r
              ON r.request_url = c.request_url
             AND r.response_sha256 = c.response_sha256
            WHERE c.accession = ? AND c.request_url = ? AND c.response_sha256 = ?
            ORDER BY r.captured_at DESC
            LIMIT 1
            """,
            (accession_text, key.request_url, key.response_sha256),
        ).fetchone()
        if row is None:
            raise IndexFixtureError(
                f"no captured page for accession {accession_text} and key {key}"
            )
        try:
            body = decompress_payload(bytes(row[2]))
        except zstd.ZstdError as exc:
            raise IndexFixtureError(
                f"captured page cannot be decompressed: {key}"
            ) from exc
        if sha256_bytes(body) != key.response_sha256:
            raise IndexFixtureError(f"captured page digest mismatch: {key}")
        return CapturedIndexPage(
            accession=AccessionNumber(accession_text),
            key=IndexResponseKey(str(row[0]), str(row[1])),
            body=body,
            captured_at=str(row[3]),
        )

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("IndexFixtureReader must be used as a context manager")
        return self._connection


def open_index_fixture(
    paths: FixturePaths,
) -> IndexFixtureReader:
    return IndexFixtureReader(paths)


def list_index_cases(
    paths: FixturePaths, accession: AccessionNumber | str
) -> tuple[CapturedIndexCase, ...]:
    with open_index_fixture(paths) as reader:
        return reader.list_cases(accession)


def replay_index_page(
    paths: FixturePaths,
    accession: AccessionNumber | str,
    key: IndexResponseKey,
) -> CapturedIndexPage:
    with open_index_fixture(paths) as reader:
        return reader.replay(accession, key)


def list_fixture(paths: FixturePaths) -> FixtureListStatus:
    if not paths.manifest_path.is_file():
        return FixtureListStatus(
            fixture_id=None,
            state="incomplete",
            schema_version=None,
            database_exists=paths.storage_path.is_file(),
            database_integrity_ok=None,
            page_count=0,
            accession_count=0,
            membership_count=0,
            contributions=(),
        )
    manifest = load_manifest(paths)
    if not paths.storage_path.is_file():
        return FixtureListStatus(
            fixture_id=manifest.fixture_id,
            state="incomplete",
            schema_version=manifest.schema_version,
            database_exists=False,
            database_integrity_ok=None,
            page_count=manifest.page_count,
            accession_count=manifest.accession_count,
            membership_count=manifest.membership_count,
            contributions=manifest.contributions,
        )
    connection = open_readonly(paths.storage_path)
    try:
        validate_database(connection, paths.storage_path, manifest.schema_version)
        return FixtureListStatus(
            fixture_id=manifest.fixture_id,
            state=manifest.capture_state,
            schema_version=manifest.schema_version,
            database_exists=True,
            database_integrity_ok=True,
            page_count=count_rows(connection, "index_responses"),
            accession_count=distinct_accession_count(connection),
            membership_count=count_rows(connection, "cohort_members"),
            contributions=manifest.contributions,
        )
    except IndexFixtureError:
        return FixtureListStatus(
            fixture_id=manifest.fixture_id,
            state="invalid",
            schema_version=manifest.schema_version,
            database_exists=True,
            database_integrity_ok=False,
            page_count=0,
            accession_count=0,
            membership_count=0,
            contributions=manifest.contributions,
        )
    finally:
        connection.close()
