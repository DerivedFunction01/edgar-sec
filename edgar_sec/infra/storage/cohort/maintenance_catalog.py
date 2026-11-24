"""Cohort catalog opening and schema audit for maintenance."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .paths import CohortPaths

__all__ = ["CatalogUnavailableError"]


_COHORT_DIR_RE = re.compile(r"^c-[0-9a-f]{16}$")


_REQUIRED_COHORT_COLUMNS = {
    "cohort_id",
    "dataset_path",
    "dataset_sha256",
    "pinned",
}


class CatalogUnavailableError(RuntimeError):
    pass


def _connect_existing(paths: CohortPaths, *, readonly: bool) -> sqlite3.Connection:
    mode = "ro" if readonly else "rw"
    immutable = ""
    wal = Path(f"{paths.catalog_file}-wal")
    shm = Path(f"{paths.catalog_file}-shm")
    if wal.is_symlink() or shm.is_symlink():
        raise CatalogUnavailableError("catalog WAL sidecars cannot be symlinks")
    if readonly:
        active_wal = wal.is_file() and wal.stat().st_size > 0
        if active_wal and not shm.is_file():
            raise CatalogUnavailableError(
                "cannot audit an active WAL without its shared-memory index "
                "in read-only mode"
            )
        if not active_wal and not shm.is_file():
            immutable = "&immutable=1"
    uri = f"{paths.catalog_file.absolute().as_uri()}?mode={mode}{immutable}"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if readonly:
            connection.execute("PRAGMA query_only = ON")
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise CatalogUnavailableError(f"cannot open catalog: {exc}") from exc
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('cohorts', 'cohort_tags', 'source_active_pointers', "
            "'active_family_indices', 'detached_cohort_datasets')"
        )
    }


def _check_catalog(connection: sqlite3.Connection) -> tuple[str, ...]:
    findings: list[str] = []
    try:
        integrity = [
            str(row[0]) for row in connection.execute("PRAGMA integrity_check")
        ]
        if integrity != ["ok"]:
            findings.extend(f"SQLite integrity_check: {result}" for result in integrity)
        tables = _table_names(connection)
        required = (
            ("cohorts", "PRAGMA table_info(cohorts)", _REQUIRED_COHORT_COLUMNS),
            ("cohort_tags", "PRAGMA table_info(cohort_tags)", {"cohort_id", "tag"}),
            (
                "source_active_pointers",
                "PRAGMA table_info(source_active_pointers)",
                {"source_name", "active_snapshot_id"},
            ),
            (
                "active_family_indices",
                "PRAGMA table_info(active_family_indices)",
                {
                    "universe_cohort_id",
                    "family_index_id",
                    "rules_fingerprint",
                    "dataset_path",
                    "dataset_sha256",
                },
            ),
            (
                "detached_cohort_datasets",
                "PRAGMA table_info(detached_cohort_datasets)",
                {"cohort_id", "dataset_path", "detached_at"},
            ),
        )
        for table, pragma, required_columns in required:
            if table not in tables:
                if table in {
                    "cohorts",
                    "cohort_tags",
                    "source_active_pointers",
                    "active_family_indices",
                }:
                    findings.append(f"catalog schema is missing the {table} table")
                continue
            columns = {str(row[1]) for row in connection.execute(pragma)}
            missing = sorted(required_columns - columns)
            if missing:
                findings.append(f"catalog schema is missing {table} columns: {missing}")
        if "cohort_tags" in tables:
            findings.extend(
                f"cohort tag foreign-key violation: {tuple(row)}"
                for row in connection.execute("PRAGMA foreign_key_check(cohort_tags)")
            )
        if "active_family_indices" in tables:
            findings.extend(
                f"family-index foreign-key violation: {tuple(row)}"
                for row in connection.execute(
                    "PRAGMA foreign_key_check(active_family_indices)"
                )
            )
    except sqlite3.Error as exc:
        findings.append(f"catalog schema audit failed: {exc}")
    return tuple(findings)


def _detached_ids(connection: sqlite3.Connection, tables: set[str]) -> set[str]:
    if "detached_cohort_datasets" not in tables:
        return set()
    return {
        str(row[0])
        for row in connection.execute("SELECT cohort_id FROM detached_cohort_datasets")
    }
