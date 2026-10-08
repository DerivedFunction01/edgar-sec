"""WAL-backed cohort metadata catalog and publication safeguards."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import uuid
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json

from .models import CohortRecord
from .paths import CohortPaths, STAGING_PREFIX

MANIFEST_SCHEMA_VERSION = "2.0.0"
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

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
"""


class CohortCatalogError(ValueError):
    """A cohort catalog operation violates an identity or lifecycle rule."""


class CohortCollisionError(CohortCatalogError):
    """A 16-hex cohort identifier is already bound to another roster."""


class CohortPinnedError(CohortCatalogError):
    """A pinned cohort cannot be deleted."""


class CohortActiveSourceError(CohortCatalogError):
    """A cohort referenced by an active source pointer cannot be deleted."""


class CohortInUseError(CohortCatalogError):
    """A cohort referenced by a workspace alias cannot be deleted."""


class CohortIdentifierError(CohortCatalogError):
    """A cohort identifier is missing, too short, or ambiguous."""


class CohortCatalog:
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
        if not _HEX_SHA256_RE.fullmatch(roster_id):
            raise ValueError("roster_id must be a lowercase SHA-256 digest")
        source_details = origin_details or {}
        identity_digest = roster_id
        if origin_kind == "official_source":
            identity_digest = source_details.get("source_snapshot_id", "")
            if not isinstance(identity_digest, str) or not _HEX_SHA256_RE.fullmatch(
                identity_digest
            ):
                raise ValueError(
                    "official source cohorts require a SHA-256 source_snapshot_id"
                )
        if cohort_id != f"c-{identity_digest[:16]}":
            raise ValueError(
                "cohort_id must be c- followed by the identity digest's first 16 hex digits"
            )
        if not _HEX_SHA256_RE.fullmatch(dataset_sha256):
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
                self.write_manifest(record)
            return record
        except BaseException:
            if registration_started and final_dir.exists():
                try:
                    concurrently_registered = self.get_cohort(cohort_id) is not None
                except sqlite3.Error:
                    concurrently_registered = True
                if not concurrently_registered:
                    shutil.rmtree(final_dir, ignore_errors=True)
            raise

    def write_manifest(
        self, record: CohortRecord, directory: Path | str | None = None
    ) -> Path:
        target_dir = (
            self.paths.cohort_dir(record.cohort_id)
            if directory is None
            else Path(directory).resolve()
        )
        root = self.paths.cohorts_root.resolve()
        if target_dir.parent != root:
            raise ValueError(
                "manifest directory must be a direct child of cohorts_root"
            )
        if target_dir != self.paths.cohort_dir(
            record.cohort_id
        ) and not target_dir.name.startswith(f"{STAGING_PREFIX}{record.cohort_id}-"):
            raise ValueError("manifest directory must be this cohort or its stage")
        manifest_path = target_dir / "cohort.json"
        atomic_write_json(manifest_path, record.to_manifest())
        return manifest_path

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

    def list_cohorts(
        self,
        *,
        tag: str | None = None,
        pinned_only: bool = False,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CohortRecord]:
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be non-negative")
        pattern = f"%{search}%" if search is not None else None
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.* FROM cohorts AS c
                WHERE (? IS NULL OR EXISTS (
                    SELECT 1 FROM cohort_tags AS t
                    WHERE t.cohort_id = c.cohort_id AND t.tag = ?
                ))
                AND (? = 0 OR c.pinned = 1)
                AND (? IS NULL OR c.cohort_id LIKE ? OR c.name LIKE ? OR c.description LIKE ?)
                ORDER BY c.created_at DESC, c.cohort_id
                LIMIT ? OFFSET ?
                """,
                (
                    tag,
                    tag,
                    int(pinned_only),
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    limit,
                    offset,
                ),
            ).fetchall()
            return [self._record(connection, row) for row in rows]

    def rename_cohort(self, cohort_id: str, new_name: str) -> None:
        if not new_name:
            raise ValueError("cohort name must be non-empty")
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE cohorts SET name = ?, updated_at = ? WHERE cohort_id = ?",
                (new_name, datetime.now(UTC).isoformat(), cohort_id),
            )
            if cursor.rowcount == 0:
                raise CohortIdentifierError(f"Cohort not found: {cohort_id!r}")
            row = connection.execute(
                "SELECT * FROM cohorts WHERE cohort_id = ?", (cohort_id,)
            ).fetchone()
            self.write_manifest(self._record(connection, row))

    def add_tags(self, cohort_id: str, tags: Sequence[str]) -> None:
        if any(not isinstance(tag, str) or not tag for tag in tags):
            raise ValueError("cohort tags must be non-empty strings")
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM cohorts WHERE cohort_id = ?", (cohort_id,)
                ).fetchone()
                is None
            ):
                raise CohortIdentifierError(f"Cohort not found: {cohort_id!r}")
            connection.executemany(
                "INSERT OR IGNORE INTO cohort_tags (cohort_id, tag, created_at) VALUES (?, ?, ?)",
                ((cohort_id, tag, now) for tag in set(tags)),
            )
            connection.execute(
                "UPDATE cohorts SET updated_at = ? WHERE cohort_id = ?",
                (now, cohort_id),
            )
            row = connection.execute(
                "SELECT * FROM cohorts WHERE cohort_id = ?", (cohort_id,)
            ).fetchone()
            self.write_manifest(self._record(connection, row))

    def remove_tags(self, cohort_id: str, tags: Sequence[str]) -> None:
        if any(not isinstance(tag, str) or not tag for tag in tags):
            raise ValueError("cohort tags must be non-empty strings")
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM cohorts WHERE cohort_id = ?", (cohort_id,)
                ).fetchone()
                is None
            ):
                raise CohortIdentifierError(f"Cohort not found: {cohort_id!r}")
            connection.executemany(
                "DELETE FROM cohort_tags WHERE cohort_id = ? AND tag = ?",
                ((cohort_id, tag) for tag in set(tags)),
            )
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "UPDATE cohorts SET updated_at = ? WHERE cohort_id = ?",
                (now, cohort_id),
            )
            row = connection.execute(
                "SELECT * FROM cohorts WHERE cohort_id = ?", (cohort_id,)
            ).fetchone()
            self.write_manifest(self._record(connection, row))

    def delete_cohort(
        self,
        cohort_id: str,
        purge_dataset: bool = True,
        *,
        force: bool = False,
    ) -> bool:
        quarantined: Path | None = None
        final_dir = self.paths.cohort_dir(cohort_id)
        deleted = False
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT pinned FROM cohorts WHERE cohort_id = ?", (cohort_id,)
                ).fetchone()
                if row is None:
                    return False
                if row["pinned"]:
                    raise CohortPinnedError(f"Cohort {cohort_id!r} is pinned")
                if self._table_exists(connection, "source_active_pointers"):
                    active = connection.execute(
                        "SELECT source_name FROM source_active_pointers WHERE active_snapshot_id = ? LIMIT 1",
                        (cohort_id,),
                    ).fetchone()
                    if active is not None:
                        raise CohortActiveSourceError(
                            f"Cohort {cohort_id!r} is active for source {active['source_name']!r}"
                        )
                aliases_exist = self._table_exists(connection, "object_session_aliases")
                if aliases_exist:
                    alias = connection.execute(
                        "SELECT session_id, alias_name FROM object_session_aliases WHERE target_id = ? LIMIT 1",
                        (cohort_id,),
                    ).fetchone()
                    if alias is not None and not force:
                        raise CohortInUseError(
                            f"Cohort {cohort_id!r} is referenced by a workspace alias"
                        )
                if purge_dataset and final_dir.exists():
                    resolved_root = self.paths.cohorts_root.resolve()
                    target = final_dir.resolve()
                    if target.parent != resolved_root:
                        raise ValueError("cohort purge target escapes cohorts root")
                    quarantined = (
                        resolved_root
                        / f"{STAGING_PREFIX}purge-{cohort_id}-{uuid.uuid4().hex}"
                    )
                    final_dir.rename(quarantined)
                if aliases_exist and force:
                    connection.execute(
                        "DELETE FROM object_session_aliases WHERE target_id = ?",
                        (cohort_id,),
                    )
                connection.execute(
                    "DELETE FROM cohorts WHERE cohort_id = ?", (cohort_id,)
                )
            deleted = True
        except BaseException:
            if (
                quarantined is not None
                and quarantined.exists()
                and not final_dir.exists()
            ):
                quarantined.rename(final_dir)
            raise
        if quarantined is not None:
            shutil.rmtree(quarantined)
        return deleted

    def resolve_cohort_identifier(
        self, id_or_name: str, *, min_prefix_len: int = 7
    ) -> CohortRecord:
        if min_prefix_len < 1:
            raise ValueError("min_prefix_len must be positive")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM cohorts WHERE name = ? LIMIT 1", (id_or_name,)
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT * FROM cohorts WHERE cohort_id = ? LIMIT 1", (id_or_name,)
                ).fetchone()
            if row is not None:
                return self._record(connection, row)
            prefix = id_or_name[2:] if id_or_name.startswith("c-") else id_or_name
            if len(prefix) < min_prefix_len:
                raise CohortIdentifierError(
                    f"Ambiguous or short hash prefix {id_or_name!r}; hash lookups require at least {min_prefix_len} characters"
                )
            if not re.fullmatch(r"[0-9a-fA-F]+", prefix):
                raise CohortIdentifierError(f"Cohort not found: {id_or_name!r}")
            rows = connection.execute(
                "SELECT * FROM cohorts WHERE cohort_id LIKE ? OR cohort_id LIKE ? ORDER BY cohort_id",
                (f"c-{prefix}%", f"{prefix}%"),
            ).fetchall()
            if not rows:
                raise CohortIdentifierError(f"Cohort not found: {id_or_name!r}")
            if len(rows) > 1:
                matches = ", ".join(row["cohort_id"] for row in rows)
                raise CohortIdentifierError(
                    f"Ambiguous cohort prefix {id_or_name!r}; matches {len(rows)} cohorts: [{matches}]"
                )
            return self._record(connection, rows[0])

    def set_active_source_pointer(
        self, source_name: str, active_snapshot_id: str
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO source_active_pointers (source_name, active_snapshot_id, pinned_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    active_snapshot_id = excluded.active_snapshot_id,
                    pinned_at = excluded.pinned_at
                """,
                (source_name, active_snapshot_id, datetime.now(UTC).isoformat()),
            )

    def get_active_source_pointer(self, source_name: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT active_snapshot_id FROM source_active_pointers WHERE source_name = ?",
                (source_name,),
            ).fetchone()
            return str(row["active_snapshot_id"]) if row is not None else None

    def cleanup_stale_staging(self, max_age_seconds: int = 86_400) -> int:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative")
        cutoff = datetime.now(UTC).timestamp() - max_age_seconds
        removed = 0
        for stage in self.paths.list_staging_dirs():
            try:
                if stage.stat().st_mtime < cutoff:
                    if stage.name.startswith(f"{STAGING_PREFIX}purge-"):
                        cohort_id = stage.name.removeprefix(
                            f"{STAGING_PREFIX}purge-"
                        ).rsplit("-", 1)[0]
                        if self.get_cohort(cohort_id) is not None:
                            final_dir = self.paths.cohort_dir(cohort_id)
                            if not final_dir.exists():
                                stage.rename(final_dir)
                                continue
                    self.paths.remove_staging_dir(stage)
                    removed += 1
            except FileNotFoundError:
                continue
        return removed


__all__ = [
    "CohortActiveSourceError",
    "CohortCatalog",
    "CohortCatalogError",
    "CohortCollisionError",
    "CohortIdentifierError",
    "CohortInUseError",
    "CohortPinnedError",
    "MANIFEST_SCHEMA_VERSION",
]
