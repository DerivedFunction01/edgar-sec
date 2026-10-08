from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.maintenance import (
    CatalogUnavailableError,
    audit_cohort_store,
    maintain_cohort_store,
)
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.infra.storage.object_store.store import ObjectStore


def _registered(
    catalog: CohortCatalog,
    paths: CohortPaths,
    suffix: str,
    *,
    pinned: bool = False,
):
    roster_id = hashlib.sha256(suffix.encode()).hexdigest()
    cohort_id = f"c-{roster_id[:16]}"
    dataset = paths.cohort_dataset_file(cohort_id)
    dataset.parent.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "ordinal": pa.array([0, 1], type=pa.int64()),
                "cik_padded": pa.array(["0000000001", "0000000002"]),
                "name": pa.array(["One", "Two"]),
            }
        ),
        dataset,
    )
    return catalog.register_cohort(
        cohort_id=cohort_id,
        origin_kind="file_import",
        origin_details={"source": suffix},
        roster_id=roster_id,
        row_count=2,
        distinct_cik_count=2,
        dataset_sha256=file_sha256(dataset),
        dataset_path=paths.relative_path(dataset),
        pinned=pinned,
    )


def test_doctor_is_read_only_and_audits_registered_parquet(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    _registered(catalog, paths, "healthy")
    before = {
        entry.name: (entry.stat().st_mtime_ns, entry.stat().st_size)
        for entry in paths.cohorts_root.iterdir()
    }

    report = audit_cohort_store(paths)

    after = {
        entry.name: (entry.stat().st_mtime_ns, entry.stat().st_size)
        for entry in paths.cohorts_root.iterdir()
    }
    assert report.healthy
    assert before == after


def test_doctor_reads_committed_wal_without_creating_sidecars(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    CohortCatalog(paths)
    writer = sqlite3.connect(paths.catalog_file)
    writer.execute("PRAGMA journal_mode = WAL")
    writer.execute(
        "INSERT INTO detached_cohort_datasets "
        "(cohort_id, dataset_path, dataset_sha256, detached_at) VALUES (?, ?, ?, ?)",
        (
            "c-0123456789abcdef",
            "c-0123456789abcdef/ciks.parquet",
            "0" * 64,
            "now",
        ),
    )
    writer.commit()
    before = {
        entry.name: (entry.stat().st_mtime_ns, entry.stat().st_size)
        for entry in paths.cohorts_root.iterdir()
    }

    report = audit_cohort_store(paths)

    after = {
        entry.name: (entry.stat().st_mtime_ns, entry.stat().st_size)
        for entry in paths.cohorts_root.iterdir()
    }
    writer.close()
    assert "detached catalog entry has no marked dataset" in " ".join(report.findings)
    assert before == after


def test_doctor_does_not_initialize_missing_optional_table(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    CohortCatalog(paths)
    with sqlite3.connect(paths.catalog_file) as connection:
        connection.execute("DROP TABLE detached_cohort_datasets")
    before = {
        entry.name: (entry.stat().st_mtime_ns, entry.stat().st_size)
        for entry in paths.cohorts_root.iterdir()
    }

    report = audit_cohort_store(paths)

    after = {
        entry.name: (entry.stat().st_mtime_ns, entry.stat().st_size)
        for entry in paths.cohorts_root.iterdir()
    }
    with sqlite3.connect(paths.catalog_file) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'detached_cohort_datasets'"
            ).fetchone()
            is None
        )
    assert report.healthy
    assert before == after


def test_doctor_reports_corrupt_and_uncataloged_artifacts(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths, "broken")
    paths.resolve_relative_path(record.dataset_path).write_bytes(b"not parquet")
    orphan = paths.cohort_dir("c-0123456789abcdef")
    orphan.mkdir()

    report = audit_cohort_store(paths)

    assert not report.healthy
    assert any("checksum mismatch" in finding for finding in report.findings)
    assert any("corrupt Parquet" in finding for finding in report.findings)
    assert any("uncataloged cohort directory" in finding for finding in report.findings)


def test_doctor_audits_active_family_index_artifacts(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    universe = _registered(catalog, paths, "family-index-doctor")
    family_index_id = "a" * 32
    family_path = paths.family_index_file(family_index_id)
    family_path.parent.mkdir(parents=True)
    family_path.write_bytes(b"not parquet")
    with sqlite3.connect(paths.catalog_file) as connection:
        connection.execute(
            "INSERT INTO active_family_indices "
            "(universe_cohort_id, family_index_id, rules_fingerprint, dataset_path, "
            "dataset_sha256) VALUES (?, ?, ?, ?, ?)",
            (
                universe.cohort_id,
                family_index_id,
                "b" * 64,
                paths.relative_path(family_path),
                file_sha256(family_path),
            ),
        )

    report = audit_cohort_store(paths)

    assert any("corrupt family-index Parquet" in item for item in report.findings)


def test_orphan_sweep_skips_detached_directories(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    CohortCatalog(paths)
    orphan = paths.cohort_dir("c-0123456789abcdef")
    orphan.mkdir(parents=True)
    detached = paths.cohort_dir("c-fedcba9876543210")
    detached.mkdir()
    (detached / ".detached").touch()

    report = maintain_cohort_store(paths, clean_orphans=True)

    assert dict(report.removed)["orphans"] == 1
    assert not orphan.exists()
    assert detached.is_dir()


def test_all_excludes_detached_and_raw_snapshot_cleanup(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    missing = _registered(catalog, paths, "all-missing")
    paths.resolve_relative_path(missing.dataset_path).unlink()
    orphan = paths.cohort_dir("c-0123456789abcdef")
    orphan.mkdir()
    detached = paths.cohort_dir("c-fedcba9876543210")
    detached.mkdir()
    (detached / ".detached").touch()
    snapshots = paths.cohorts_root / "source_snapshots"
    snapshots.mkdir()
    (snapshots / "keep.json").write_text("{}", encoding="utf-8")

    report = maintain_cohort_store(paths, all=True)

    assert dict(report.removed) == {"missing": 1, "orphans": 2, "staging": 0}
    assert catalog.get_cohort(missing.cohort_id) is None
    assert not orphan.exists()
    assert not paths.cohort_dir(missing.cohort_id).exists()
    assert detached.is_dir()
    assert snapshots.is_dir()


def test_clean_missing_ignores_workspace_aliases_and_keeps_protected_rows(
    tmp_path: Path,
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    missing = _registered(catalog, paths, "missing")
    pinned = _registered(catalog, paths, "pinned", pinned=True)
    active = _registered(catalog, paths, "active")
    missing_path = paths.resolve_relative_path(missing.dataset_path)
    paths.resolve_relative_path(pinned.dataset_path).unlink()
    paths.resolve_relative_path(active.dataset_path).unlink()
    missing_path.unlink()
    store = ObjectStore(paths.catalog_file)
    store.initialize_schema()
    store.touch_session("saved")
    store.upsert_alias("saved", "A", missing.cohort_id)
    with sqlite3.connect(paths.catalog_file) as connection:
        connection.execute(
            "INSERT INTO source_active_pointers (source_name, active_snapshot_id) "
            "VALUES (?, ?)",
            ("cik_lookup", active.cohort_id),
        )

    report = maintain_cohort_store(paths, clean_missing=True)

    assert dict(report.removed)["missing"] == 1
    assert catalog.get_cohort(missing.cohort_id) is None
    assert catalog.get_cohort(pinned.cohort_id) is not None
    assert catalog.get_cohort(active.cohort_id) is not None
    assert store.get_alias_target("saved", "A") == missing.cohort_id
    assert len(report.warnings) == 2


def test_clean_missing_preserves_active_family_index_universe(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths, "family-index-universe")
    paths.resolve_relative_path(record.dataset_path).unlink()
    with sqlite3.connect(paths.catalog_file) as connection:
        connection.execute(
            "INSERT INTO active_family_indices "
            "(universe_cohort_id, family_index_id, rules_fingerprint, dataset_path, "
            "dataset_sha256) VALUES (?, ?, ?, ?, ?)",
            (record.cohort_id, "a" * 32, "b" * 64, "family_index/x.parquet", "c" * 64),
        )

    report = maintain_cohort_store(paths, clean_missing=True)

    assert dict(report.removed)["missing"] == 0
    assert catalog.get_cohort(record.cohort_id) is not None


def test_detached_delete_registers_and_explicit_cleanup_removes_dataset(
    tmp_path: Path,
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths, "detached")
    dataset_dir = paths.cohort_dir(record.cohort_id)

    assert catalog.delete_cohort(record.cohort_id, purge_dataset=False)
    assert catalog.get_cohort(record.cohort_id) is None
    assert (dataset_dir / ".detached").is_file()
    with sqlite3.connect(paths.catalog_file) as connection:
        assert connection.execute(
            "SELECT dataset_path, dataset_sha256 FROM detached_cohort_datasets "
            "WHERE cohort_id = ?",
            (record.cohort_id,),
        ).fetchone() == (record.dataset_path, record.dataset_sha256)
    assert audit_cohort_store(paths).healthy
    paths.resolve_relative_path(record.dataset_path).write_bytes(
        b"corrupt detached data"
    )
    assert any(
        "detached dataset checksum mismatch" in finding
        for finding in audit_cohort_store(paths).findings
    )

    skipped = maintain_cohort_store(paths, clean_orphans=True)
    assert dict(skipped.removed)["orphans"] == 0
    assert dataset_dir.is_dir()
    removed = maintain_cohort_store(paths, clean_detached=True)
    assert dict(removed.removed)["detached"] == 1
    assert not dataset_dir.exists()
    with sqlite3.connect(paths.catalog_file) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM detached_cohort_datasets"
            ).fetchone()[0]
            == 0
        )


def test_detached_registry_migration_backfills_dataset_digest(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths, "detached-migration")
    dataset = paths.resolve_relative_path(record.dataset_path)
    with sqlite3.connect(paths.catalog_file) as connection:
        connection.execute("DROP TABLE detached_cohort_datasets")
        connection.execute(
            "CREATE TABLE detached_cohort_datasets (cohort_id TEXT PRIMARY KEY, "
            "dataset_path TEXT NOT NULL, detached_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO detached_cohort_datasets VALUES (?, ?, ?)",
            (record.cohort_id, record.dataset_path, "now"),
        )

    catalog.initialize_schema()

    with sqlite3.connect(paths.catalog_file) as connection:
        assert connection.execute(
            "SELECT dataset_sha256 FROM detached_cohort_datasets WHERE cohort_id = ?",
            (record.cohort_id,),
        ).fetchone() == (file_sha256(dataset),)


def test_detached_cleanup_preserves_unmarked_directory(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    CohortCatalog(paths)
    directory = paths.cohort_dir("c-0123456789abcdef")
    directory.mkdir(parents=True)
    dataset = paths.cohort_dataset_file(directory.name)
    with sqlite3.connect(paths.catalog_file) as connection:
        connection.execute(
            "INSERT INTO detached_cohort_datasets "
            "(cohort_id, dataset_path, dataset_sha256, detached_at) "
            "VALUES (?, ?, ?, ?)",
            (
                directory.name,
                paths.relative_path(dataset),
                "0" * 64,
                "now",
            ),
        )

    report = maintain_cohort_store(paths, clean_detached=True)

    assert dict(report.removed)["detached"] == 0
    assert directory.is_dir()
    assert any(
        "preserved unmarked detached directory" in item for item in report.warnings
    )


def test_raw_snapshot_cleanup_is_explicit_and_scoped(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    CohortCatalog(paths)
    snapshots = paths.cohorts_root / "source_snapshots"
    snapshots.mkdir()
    (snapshots / "old.json").write_text("{}", encoding="utf-8")
    unrelated = paths.cohorts_root / "family_index"
    unrelated.mkdir()
    (unrelated / "keep.parquet").write_bytes(b"keep")

    report = maintain_cohort_store(paths, clean_raw_snapshots=True)

    assert dict(report.removed)["raw_snapshots"] == 1
    assert not snapshots.exists()
    assert (unrelated / "keep.parquet").is_file()


def test_maintenance_fails_closed_on_corrupt_catalog(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    CohortCatalog(paths)
    orphan = paths.cohort_dir("c-0123456789abcdef")
    orphan.mkdir()
    paths.catalog_file.write_bytes(b"not a sqlite database")

    with pytest.raises(CatalogUnavailableError, match="catalog schema audit failed"):
        maintain_cohort_store(paths, clean_orphans=True)
    assert orphan.is_dir()
