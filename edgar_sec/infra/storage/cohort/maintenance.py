"""Read-only cohort diagnostics and explicit filesystem cleanup."""

from __future__ import annotations

import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)

from .paths import (
    MAX_STAGING_LEASE_SECONDS,
    STAGING_PREFIX,
    STAGING_QUARANTINE_EXPIRY_SECONDS,
    STAGING_QUARANTINE_PREFIX,
    CohortPaths,
)

_COHORT_DIR_RE = re.compile(r"^c-[0-9a-f]{16}$")
_REQUIRED_COHORT_COLUMNS = {
    "cohort_id",
    "dataset_path",
    "dataset_sha256",
    "pinned",
}


class CatalogUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuditReport:
    findings: tuple[str, ...]
    catalog_present: bool

    @property
    def healthy(self) -> bool:
        return self.catalog_present and not self.findings


@dataclass(frozen=True, slots=True)
class MaintenanceReport:
    removed: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]


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


def _resolved_dataset(paths: CohortPaths, dataset_path: str) -> Path:
    target = paths.resolve_relative_path(dataset_path)
    lexical = paths.cohorts_root.joinpath(*Path(dataset_path).parts)
    cursor = paths.cohorts_root
    for part in Path(dataset_path).parts:
        if cursor.is_symlink():
            raise ValueError(
                f"cohort dataset path contains a symlink: {dataset_path!r}"
            )
        cursor = cursor / part
    if lexical.is_symlink():
        raise ValueError(f"cohort dataset path is a symlink: {dataset_path!r}")
    return target


def _parquet_findings(dataset: Path, row_count: int | None = None) -> tuple[str, ...]:
    try:
        parquet = pq.ParquetFile(dataset)
        schema = parquet.schema_arrow
        expected = {
            "ordinal": pa.int64(),
            "cik_padded": pa.string(),
            "name": pa.string(),
        }
        for column, data_type in expected.items():
            if column not in schema.names or schema.field(column).type != data_type:
                return (f"invalid Parquet schema in {dataset}",)
        actual_rows = 0
        for batch in parquet.iter_batches(batch_size=resolve_parquet_read_batch_size()):
            actual_rows += batch.num_rows
        if row_count is not None and actual_rows != row_count:
            return (
                f"Parquet row count mismatch in {dataset}: {actual_rows} != {row_count}",
            )
    except Exception as exc:
        return (f"corrupt Parquet file {dataset}: {exc}",)
    return ()


def _family_index_findings(dataset: Path) -> tuple[str, ...]:
    expected = {
        "cik",
        "company_family",
        "family_kind",
        "sponsor_key",
        "assignment_rule",
    }
    try:
        parquet = pq.ParquetFile(dataset)
        if not expected.issubset(parquet.schema_arrow.names):
            return (f"invalid family-index schema in {dataset}",)
        for _ in parquet.iter_batches(batch_size=resolve_parquet_read_batch_size()):
            pass
    except Exception as exc:
        return (f"corrupt family-index Parquet file {dataset}: {exc}",)
    return ()


def _detached_ids(connection: sqlite3.Connection, tables: set[str]) -> set[str]:
    if "detached_cohort_datasets" not in tables:
        return set()
    return {
        str(row[0])
        for row in connection.execute("SELECT cohort_id FROM detached_cohort_datasets")
    }


def audit_cohort_store(paths: CohortPaths) -> AuditReport:
    if paths.catalog_file.is_symlink():
        return AuditReport((f"catalog path is a symlink: {paths.catalog_file}",), True)
    if not paths.catalog_file.is_file():
        return AuditReport((f"catalog is absent: {paths.catalog_file}",), False)
    findings: list[str] = []
    try:
        connection = _connect_existing(paths, readonly=True)
    except CatalogUnavailableError as exc:
        return AuditReport((str(exc),), True)
    try:
        findings.extend(_check_catalog(connection))
        if any(
            "schema is missing" in item or "schema audit failed" in item
            for item in findings
        ):
            return AuditReport(tuple(findings), True)
        tables = _table_names(connection)
        rows = connection.execute(
            "SELECT cohort_id, dataset_path, dataset_sha256, row_count "
            "FROM cohorts ORDER BY cohort_id"
        ).fetchall()
        for row in rows:
            cohort_id = str(row["cohort_id"])
            try:
                dataset = _resolved_dataset(paths, str(row["dataset_path"]))
            except (OSError, ValueError) as exc:
                findings.append(f"unsafe dataset path for {cohort_id}: {exc}")
                continue
            if not dataset.is_file():
                findings.append(
                    f"missing dataset for {cohort_id}: {row['dataset_path']}"
                )
                continue
            try:
                digest = file_sha256(dataset)
            except OSError as exc:
                findings.append(f"cannot hash dataset for {cohort_id}: {exc}")
                continue
            if digest != row["dataset_sha256"]:
                findings.append(f"dataset checksum mismatch for {cohort_id}")
            findings.extend(_parquet_findings(dataset, int(row["row_count"])))

        if "active_family_indices" in tables:
            family_rows = connection.execute(
                "SELECT family_index_id, dataset_path, dataset_sha256 "
                "FROM active_family_indices ORDER BY family_index_id"
            ).fetchall()
            for row in family_rows:
                family_index_id = str(row["family_index_id"])
                try:
                    dataset = _resolved_dataset(paths, str(row["dataset_path"]))
                    if dataset != paths.family_index_file(family_index_id):
                        raise ValueError(
                            "dataset path does not match its family-index ID"
                        )
                except (OSError, ValueError) as exc:
                    findings.append(
                        f"unsafe family-index path for {family_index_id}: {exc}"
                    )
                    continue
                if not dataset.is_file():
                    findings.append(f"missing family-index dataset: {family_index_id}")
                    continue
                try:
                    digest = file_sha256(dataset)
                except OSError as exc:
                    findings.append(
                        f"cannot hash family-index dataset {family_index_id}: {exc}"
                    )
                    continue
                if digest != row["dataset_sha256"]:
                    findings.append(
                        f"family-index checksum mismatch: {family_index_id}"
                    )
                findings.extend(_family_index_findings(dataset))

        detached_rows = {}
        if "detached_cohort_datasets" in tables:
            detached_columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(detached_cohort_datasets)"
                )
            }
            detached_query = (
                "SELECT cohort_id, dataset_path, dataset_sha256 "
                "FROM detached_cohort_datasets"
                if "dataset_sha256" in detached_columns
                else "SELECT cohort_id, dataset_path, '' AS dataset_sha256 "
                "FROM detached_cohort_datasets"
            )
            detached_rows = {
                str(row["cohort_id"]): (
                    str(row["dataset_path"]),
                    str(row["dataset_sha256"]),
                )
                for row in connection.execute(detached_query)
            }
        detached_ids = set(detached_rows)
        for cohort_id, (dataset_path, expected_digest) in sorted(detached_rows.items()):
            if not _COHORT_DIR_RE.fullmatch(cohort_id):
                findings.append(f"invalid detached cohort identifier: {cohort_id!r}")
                continue
            detached_dir = paths.cohorts_root / cohort_id
            marker = detached_dir / ".detached"
            if (
                detached_dir.is_symlink()
                or not detached_dir.is_dir()
                or marker.is_symlink()
                or not marker.is_file()
            ):
                findings.append(
                    f"detached catalog entry has no marked dataset: {cohort_id}"
                )
            try:
                detached_dataset = _resolved_dataset(paths, dataset_path)
            except (OSError, ValueError) as exc:
                findings.append(f"unsafe detached dataset path for {cohort_id}: {exc}")
            else:
                if not detached_dataset.is_file():
                    findings.append(f"missing detached dataset for {cohort_id}")
                elif not expected_digest:
                    findings.append(
                        f"detached dataset checksum unavailable for {cohort_id}"
                    )
                else:
                    try:
                        digest = file_sha256(detached_dataset)
                    except OSError as exc:
                        findings.append(
                            f"cannot hash detached dataset {cohort_id}: {exc}"
                        )
                    else:
                        if digest != expected_digest:
                            findings.append(
                                f"detached dataset checksum mismatch for {cohort_id}"
                            )
                    findings.extend(_parquet_findings(detached_dataset))

        known_ids = {str(row["cohort_id"]) for row in rows}
        for directory in paths.cohorts_root.iterdir():
            if directory.is_symlink() or not directory.is_dir():
                continue
            marker = directory / ".detached"
            if (
                _COHORT_DIR_RE.fullmatch(directory.name)
                and marker.is_file()
                and directory.name not in detached_ids
            ):
                findings.append(
                    f"detached sentinel has no catalog entry: {directory.name}"
                )
            if (
                _COHORT_DIR_RE.fullmatch(directory.name)
                and directory.name not in known_ids
            ):
                if directory.name not in detached_ids and not marker.is_file():
                    findings.append(f"uncataloged cohort directory: {directory.name}")
            if directory.name.startswith(STAGING_PREFIX):
                if directory.name.startswith(STAGING_QUARANTINE_PREFIX):
                    findings.append(f"quarantined staging directory: {directory.name}")
                elif directory.name.startswith(f"{STAGING_PREFIX}purge-"):
                    findings.append(
                        f"abandoned purge staging directory: {directory.name}"
                    )
                else:
                    lease_state = paths.staging_lease_is_unexpired(directory)
                    if lease_state is None:
                        findings.append(f"unparseable staging lease: {directory.name}")
                    elif not lease_state:
                        findings.append(f"expired staging lease: {directory.name}")
    except (OSError, sqlite3.Error, ValueError) as exc:
        findings.append(f"catalog audit failed: {exc}")
    finally:
        connection.close()
    return AuditReport(tuple(findings), True)


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


def maintain_cohort_store(
    paths: CohortPaths,
    *,
    clean_stale_staging: bool = False,
    clean_orphans: bool = False,
    clean_missing: bool = False,
    clean_detached: bool = False,
    clean_raw_snapshots: bool = False,
    all: bool = False,
    force: bool = False,
) -> MaintenanceReport:
    selected = any(
        (
            clean_stale_staging,
            clean_orphans,
            clean_missing,
            clean_detached,
            clean_raw_snapshots,
            all,
        )
    )
    if not selected:
        raise ValueError("select at least one maintenance action")
    if force and not (clean_stale_staging or all):
        raise ValueError("--force requires --clean-stale-staging")
    if paths.catalog_file.is_symlink():
        raise CatalogUnavailableError(
            f"catalog path is a symlink: {paths.catalog_file}"
        )
    if not paths.catalog_file.is_file():
        raise CatalogUnavailableError(f"catalog is absent: {paths.catalog_file}")

    removed: dict[str, int] = {}
    warnings: list[str] = []
    missing_ids: list[str] = []
    detached_ids: list[str] = []
    try:
        with paths.publication_lock():
            connection = _connect_existing(paths, readonly=False)
            try:
                findings = _check_catalog(connection)
                if findings:
                    raise CatalogUnavailableError("; ".join(findings))
                use_staging = clean_stale_staging or all
                if use_staging:
                    removed["staging"] = _clean_staging(
                        paths, connection, force=force, now=datetime.now(UTC)
                    )
                if clean_missing or all:
                    missing_ids = _clean_missing(connection, paths, warnings)
                    removed["missing"] = len(missing_ids)
                    if missing_ids:
                        connection.execute("BEGIN IMMEDIATE")
                        connection.executemany(
                            "DELETE FROM cohorts WHERE cohort_id = ?",
                            ((cohort_id,) for cohort_id in missing_ids),
                        )
                        connection.commit()
                if clean_orphans or all:
                    removed["orphans"] = _clean_orphans(paths, connection)
                if clean_detached:
                    removed["detached"], detached_ids = _clean_detached(
                        paths, connection, warnings
                    )
                    if detached_ids:
                        connection.execute("BEGIN IMMEDIATE")
                        connection.executemany(
                            "DELETE FROM detached_cohort_datasets WHERE cohort_id = ?",
                            ((cohort_id,) for cohort_id in detached_ids),
                        )
                        connection.commit()
                if clean_raw_snapshots:
                    removed["raw_snapshots"] = _clean_raw_snapshots(paths)
            except CatalogUnavailableError:
                connection.rollback()
                raise
            except (OSError, sqlite3.Error, ValueError) as exc:
                connection.rollback()
                raise CatalogUnavailableError(f"maintenance failed: {exc}") from exc
            finally:
                connection.close()
    except CatalogUnavailableError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise CatalogUnavailableError(f"maintenance failed: {exc}") from exc
    return MaintenanceReport(tuple(sorted(removed.items())), tuple(warnings))


__all__ = [
    "AuditReport",
    "CatalogUnavailableError",
    "MAX_STAGING_LEASE_SECONDS",
    "MaintenanceReport",
    "audit_cohort_store",
    "maintain_cohort_store",
]
