"""Filesystem cleanup passes for cohort maintenance."""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from .maintenance_catalog import _COHORT_DIR_RE, _detached_ids, _table_names
from .maintenance_datasets import _resolved_dataset
from .paths import (
    STAGING_PREFIX,
    STAGING_QUARANTINE_EXPIRY_SECONDS,
    STAGING_QUARANTINE_PREFIX,
    CohortPaths,
)


def _safe_remove_cohort_dir(paths: CohortPaths, directory: Path) -> bool:
    if directory.is_symlink() or not _COHORT_DIR_RE.fullmatch(directory.name):
        return False
    root = paths.cohorts_root.resolve()
    if directory.parent.resolve() != root:
        return False
    shutil.rmtree(directory)
    return True


def _clean_staging(
    paths: CohortPaths,
    connection: sqlite3.Connection,
    *,
    force: bool,
    now: datetime,
) -> int:
    removed = 0
    known_ids = {
        str(row[0]) for row in connection.execute("SELECT cohort_id FROM cohorts")
    }
    for stage in paths.list_staging_dirs():
        age = now.timestamp() - stage.stat().st_mtime
        if stage.name.startswith(STAGING_QUARANTINE_PREFIX):
            if force or age > STAGING_QUARANTINE_EXPIRY_SECONDS:
                paths.remove_staging_dir(stage)
                removed += 1
            continue
        if stage.name.startswith(f"{STAGING_PREFIX}purge-"):
            cohort_id = stage.name.removeprefix(f"{STAGING_PREFIX}purge-").rsplit(
                "-", 1
            )[0]
            if not _COHORT_DIR_RE.fullmatch(cohort_id):
                continue
            final_dir = paths.cohort_dir(cohort_id)
            if cohort_id in known_ids and not final_dir.exists():
                stage.rename(final_dir)
            else:
                paths.remove_staging_dir(stage)
                removed += 1
            continue
        lease_state = paths.staging_lease_is_unexpired(stage, now=now)
        if lease_state is True:
            continue
        if lease_state is None:
            quarantine = paths.cohorts_root / (
                f"{STAGING_QUARANTINE_PREFIX}{uuid.uuid4().hex}-{stage.name}"
            )
            stage.rename(quarantine)
            if force or age > STAGING_QUARANTINE_EXPIRY_SECONDS:
                paths.remove_staging_dir(quarantine)
                removed += 1
            continue
        paths.remove_staging_dir(stage)
        removed += 1
    return removed


def _clean_orphans(paths: CohortPaths, connection: sqlite3.Connection) -> int:
    known = {str(row[0]) for row in connection.execute("SELECT cohort_id FROM cohorts")}
    detached = _detached_ids(connection, _table_names(connection))
    removed = 0
    for directory in paths.cohorts_root.iterdir():
        if (
            not _COHORT_DIR_RE.fullmatch(directory.name)
            or directory.is_symlink()
            or not directory.is_dir()
            or directory.name in known
            or directory.name in detached
            or (directory / ".detached").is_file()
        ):
            continue
        removed += int(_safe_remove_cohort_dir(paths, directory))
    return removed


def _clean_missing(
    connection: sqlite3.Connection,
    paths: CohortPaths,
    warnings: list[str],
) -> list[str]:
    tables = _table_names(connection)
    active = {
        str(row[0])
        for row in connection.execute(
            "SELECT active_snapshot_id FROM source_active_pointers"
        )
    }
    family_universes = set()
    if "active_family_indices" in tables:
        family_universes = {
            str(row[0])
            for row in connection.execute(
                "SELECT universe_cohort_id FROM active_family_indices"
            )
        }
    detached = _detached_ids(connection, tables)
    rows = connection.execute(
        "SELECT cohort_id, dataset_path, pinned FROM cohorts ORDER BY cohort_id"
    ).fetchall()
    missing_ids: list[str] = []
    for row in rows:
        cohort_id = str(row["cohort_id"])
        if cohort_id in detached:
            continue
        try:
            dataset = _resolved_dataset(paths, str(row["dataset_path"]))
        except (OSError, ValueError) as exc:
            warnings.append(f"preserved unsafe dataset path for {cohort_id}: {exc}")
            continue
        if dataset.exists():
            continue
        if row["pinned"] or cohort_id in active or cohort_id in family_universes:
            reasons = []
            if row["pinned"]:
                reasons.append("pinned")
            if cohort_id in active:
                reasons.append("active source pointer")
            if cohort_id in family_universes:
                reasons.append("active family index")
            warnings.append(
                f"preserved missing cohort {cohort_id}: {', '.join(reasons)}"
            )
            continue
        missing_ids.append(cohort_id)
    return missing_ids


def _clean_detached(
    paths: CohortPaths, connection: sqlite3.Connection, warnings: list[str]
) -> tuple[int, list[str]]:
    tables = _table_names(connection)
    catalog_ids = {
        str(row[0]) for row in connection.execute("SELECT cohort_id FROM cohorts")
    }
    detached_paths = {}
    if "detached_cohort_datasets" in tables:
        detached_paths = {
            str(row["cohort_id"]): str(row["dataset_path"])
            for row in connection.execute(
                "SELECT cohort_id, dataset_path FROM detached_cohort_datasets"
            )
        }
    targets = set(detached_paths)
    if paths.cohorts_root.is_dir():
        for directory in paths.cohorts_root.iterdir():
            marker = directory / ".detached"
            if (
                _COHORT_DIR_RE.fullmatch(directory.name)
                and not directory.is_symlink()
                and directory.is_dir()
                and marker.is_file()
                and not marker.is_symlink()
            ):
                targets.add(directory.name)
    removed = 0
    detached_ids: list[str] = []
    for cohort_id in sorted(targets):
        if not _COHORT_DIR_RE.fullmatch(cohort_id):
            warnings.append(f"preserved invalid detached identifier: {cohort_id!r}")
            continue
        if cohort_id in catalog_ids:
            warnings.append(f"preserved cataloged detached directory: {cohort_id}")
            continue
        directory = paths.cohorts_root / cohort_id
        if cohort_id in detached_paths:
            try:
                recorded = _resolved_dataset(paths, detached_paths[cohort_id])
                expected = paths.cohort_dataset_file(cohort_id)
            except (OSError, ValueError) as exc:
                warnings.append(
                    f"preserved unsafe detached path for {cohort_id}: {exc}"
                )
                continue
            if recorded != expected:
                warnings.append(f"preserved mismatched detached path for {cohort_id}")
                continue
        if directory.exists():
            marker = directory / ".detached"
            if marker.is_symlink() or not marker.is_file():
                warnings.append(f"preserved unmarked detached directory: {cohort_id}")
                continue
            if not _safe_remove_cohort_dir(paths, directory):
                warnings.append(f"preserved unsafe detached directory: {cohort_id}")
                continue
            removed += 1
        if "detached_cohort_datasets" in tables:
            detached_ids.append(cohort_id)
    return removed, detached_ids


def _clean_raw_snapshots(paths: CohortPaths) -> int:
    snapshots = paths.cohorts_root / "source_snapshots"
    if snapshots.is_symlink() or not snapshots.is_dir():
        return 0
    root = paths.cohorts_root.resolve()
    if snapshots.resolve().parent != root:
        raise ValueError("raw snapshot directory escapes cohorts root")
    shutil.rmtree(snapshots)
    return 1
