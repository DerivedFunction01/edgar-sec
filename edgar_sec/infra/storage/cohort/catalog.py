"""WAL-backed cohort metadata catalog and publication safeguards."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator

from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.serialization import canonical_json

from .deletion import DeletionMixin
from .errors import CohortCollisionError
from .family_index import FamilyIndexMixin
from .metadata import MetadataMixin
from .models import CohortRecord
from .paths import CohortPaths
from .resolution import ResolutionMixin

MANIFEST_SCHEMA_VERSION = "2.0.0"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cohorts (
    cohort_id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    manifest_schema_ver TEXT NOT NULL DEFAULT '2.0.0',
    origin_kind TEXT NOT NULL,
    origin_json TEXT NOT NULL DEFAULT '{}',
    roster_id TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    distinct_cik_count INTEGER NOT NULL,
    dataset_sha256 TEXT NOT NULL,
    dataset_path TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cohorts_name ON cohorts(name);
CREATE INDEX IF NOT EXISTS idx_cohorts_pinned ON cohorts(pinned);
CREATE INDEX IF NOT EXISTS idx_cohorts_created ON cohorts(created_at);
CREATE TABLE IF NOT EXISTS cohort_tags (
    cohort_id TEXT NOT NULL REFERENCES cohorts(cohort_id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (cohort_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_cohort_tags_tag ON cohort_tags(tag);
CREATE TABLE IF NOT EXISTS source_active_pointers (
    source_name TEXT PRIMARY KEY,
    active_snapshot_id TEXT NOT NULL,
    pinned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS active_family_indices (
    universe_cohort_id TEXT NOT NULL REFERENCES cohorts(cohort_id),
    family_index_id TEXT NOT NULL,
    rules_fingerprint TEXT NOT NULL,
    dataset_path TEXT NOT NULL,
    dataset_sha256 TEXT NOT NULL,
    pinned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (universe_cohort_id)
);
CREATE TABLE IF NOT EXISTS detached_cohort_datasets (
    cohort_id TEXT PRIMARY KEY,
    dataset_path TEXT NOT NULL,
    dataset_sha256 TEXT NOT NULL,
    detached_at TEXT NOT NULL
);
"""


class CohortCatalog(FamilyIndexMixin, MetadataMixin, DeletionMixin, ResolutionMixin):
    def __init__(self, paths: CohortPaths) -> None:
        self.paths = paths
        self.initialize_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.paths.cohorts_root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.paths.catalog_file), timeout=30.0)
        try:
            connection.execute("PRAGMA page_size = 8192")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.row_factory = sqlite3.Row
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(_SCHEMA_SQL)
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(detached_cohort_datasets)"
                )
            }
            if "dataset_sha256" not in columns:
                connection.execute(
                    "ALTER TABLE detached_cohort_datasets "
                    "ADD COLUMN dataset_sha256 TEXT NOT NULL DEFAULT ''"
                )
                rows = connection.execute(
                    "SELECT cohort_id, dataset_path FROM detached_cohort_datasets"
                ).fetchall()
                for row in rows:
                    try:
                        dataset = self.paths.resolve_relative_path(row["dataset_path"])
                    except ValueError:
                        continue
                    if dataset.is_file():
                        connection.execute(
                            "UPDATE detached_cohort_datasets SET dataset_sha256 = ? "
                            "WHERE cohort_id = ?",
                            (file_sha256(dataset), row["cohort_id"]),
                        )

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", table),
        ).fetchone()
        return row is not None

    def _record(self, connection: sqlite3.Connection, row: sqlite3.Row) -> CohortRecord:
        tag_rows = connection.execute(
            "SELECT tag FROM cohort_tags WHERE cohort_id = ? ORDER BY tag",
            (row["cohort_id"],),
        ).fetchall()
        return CohortRecord(
            cohort_id=row["cohort_id"],
            name=row["name"],
            description=row["description"],
            manifest_schema_ver=row["manifest_schema_ver"],
            origin_kind=row["origin_kind"],
            origin_json=row["origin_json"],
            roster_id=row["roster_id"],
            row_count=row["row_count"],
            distinct_cik_count=row["distinct_cik_count"],
            dataset_sha256=row["dataset_sha256"],
            dataset_path=row["dataset_path"],
            pinned=bool(row["pinned"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tags=tuple(tag["tag"] for tag in tag_rows),
        )

    def register_cohort(
        self,
        *,
        cohort_id: str,
        name: str | None = None,
        description: str = "",
        origin_kind: str,
        origin_details: dict[str, Any] | None = None,
        roster_id: str,
        row_count: int,
        distinct_cik_count: int,
        dataset_sha256: str,
        dataset_path: str,
        pinned: bool = False,
        tags: Sequence[str] = (),
    ) -> CohortRecord:
        if not is_sha256_hex_digest(roster_id):
            raise ValueError("roster_id must be a lowercase SHA-256 digest")
        source_details = origin_details or {}
        identity_digest = roster_id
        if origin_kind == "official_source":
            identity_digest = source_details.get("source_snapshot_id", "")
            if not is_sha256_hex_digest(identity_digest):
                raise ValueError(
                    "official source cohorts require a SHA-256 source_snapshot_id"
                )
        if cohort_id != f"c-{identity_digest[:16]}":
            raise ValueError(
                "cohort_id must be c- followed by the identity digest's first 16 hex digits"
            )
        if not is_sha256_hex_digest(dataset_sha256):
            raise ValueError("dataset_sha256 must be a lowercase SHA-256 digest")
        if row_count < 0 or distinct_cik_count < 0 or distinct_cik_count > row_count:
            raise ValueError("cohort row counts are inconsistent")
        relative_dataset = self.paths.relative_path(
            self.paths.resolve_relative_path(dataset_path)
        )
        expected_dataset = self.paths.relative_path(
            self.paths.cohort_dataset_file(cohort_id)
        )
        if relative_dataset != expected_dataset:
            raise ValueError("dataset_path must identify the cohort's ciks.parquet")
        dataset_file = self.paths.resolve_relative_path(relative_dataset)
        if not dataset_file.is_file() or file_sha256(dataset_file) != dataset_sha256:
            raise ValueError("dataset file is missing or its digest does not match")
        origin_json = canonical_json(source_details)
        normalized_tags = tuple(sorted(set(tags)))
        if any(not isinstance(tag, str) or not tag for tag in normalized_tags):
            raise ValueError("cohort tags must be non-empty strings")
        now = datetime.now(UTC).isoformat()
        final_dir = self.paths.cohort_dir(cohort_id)
        registration_started = False
        try:
            with self._connection() as connection:
                existing = connection.execute(
                    "SELECT * FROM cohorts WHERE cohort_id = ?", (cohort_id,)
                ).fetchone()
                if existing is not None:
                    if existing["roster_id"] != roster_id:
                        raise CohortCollisionError(
                            f"cohort id {cohort_id!r} collides with another roster"
                        )
                    prior = self._record(connection, existing)
                    if (
                        prior.dataset_sha256 != dataset_sha256
                        or prior.dataset_path != relative_dataset
                    ):
                        raise ValueError(f"cohort {cohort_id!r} is immutable")
                    return prior
                registration_started = True
                connection.execute(
                    """
                    INSERT INTO cohorts (
                        cohort_id, name, description, manifest_schema_ver,
                        origin_kind, origin_json, roster_id, row_count,
                        distinct_cik_count, dataset_sha256, dataset_path, pinned,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cohort_id,
                        name,
                        description,
                        MANIFEST_SCHEMA_VERSION,
                        origin_kind,
                        origin_json,
                        roster_id,
                        row_count,
                        distinct_cik_count,
                        dataset_sha256,
                        relative_dataset,
                        int(pinned),
                        now,
                        now,
                    ),
                )
                connection.executemany(
                    "INSERT INTO cohort_tags (cohort_id, tag, created_at) VALUES (?, ?, ?)",
                    ((cohort_id, tag, now) for tag in normalized_tags),
                )
                row = connection.execute(
                    "SELECT * FROM cohorts WHERE cohort_id = ?", (cohort_id,)
                ).fetchone()
                record = self._record(connection, row)
            return record
        except BaseException:
            if registration_started and final_dir.exists():
                try:
                    concurrently_registered = self.get_cohort(cohort_id) is not None
                except sqlite3.Error:
                    concurrently_registered = True
                if not concurrently_registered:
                    with self.paths.publication_lock():
                        shutil.rmtree(final_dir, ignore_errors=True)
            raise

    def get_cohort(self, id_or_name: str) -> CohortRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM cohorts WHERE name = ? LIMIT 1", (id_or_name,)
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT * FROM cohorts WHERE cohort_id = ? LIMIT 1", (id_or_name,)
                ).fetchone()
            return self._record(connection, row) if row is not None else None


__all__ = [
    "CohortCatalog",
    "MANIFEST_SCHEMA_VERSION",
]
