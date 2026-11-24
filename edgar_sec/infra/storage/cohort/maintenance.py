"""Read-only cohort diagnostics and explicit filesystem cleanup."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from edgar_sec.foundation.hashing import file_sha256

from .maintenance_catalog import (
    CatalogUnavailableError,
    _COHORT_DIR_RE,
    _check_catalog,
    _connect_existing,
    _table_names,
)
from .maintenance_cleanup import (
    _clean_detached,
    _clean_missing,
    _clean_orphans,
    _clean_raw_snapshots,
    _clean_staging,
)
from .maintenance_datasets import (
    _family_index_findings,
    _parquet_findings,
    _resolved_dataset,
)
from .paths import (
    MAX_STAGING_LEASE_SECONDS,
    STAGING_PREFIX,
    STAGING_QUARANTINE_PREFIX,
    CohortPaths,
)

__all__ = [
    "AuditReport",
    "MAX_STAGING_LEASE_SECONDS",
    "MaintenanceReport",
    "audit_cohort_store",
    "maintain_cohort_store",
]


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
