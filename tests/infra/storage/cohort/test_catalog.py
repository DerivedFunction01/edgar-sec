import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import (
    CohortActiveSourceError,
    CohortCatalog,
    CohortCollisionError,
    CohortIdentifierError,
    CohortInUseError,
    CohortPinnedError,
)
from edgar_sec.infra.storage.cohort.paths import CohortPaths


def _registered(
    catalog: CohortCatalog,
    paths: CohortPaths,
    *,
    suffix: str = "",
    roster_id: str | None = None,
):
    roster_id = roster_id or hashlib.sha256(("roster" + suffix).encode()).hexdigest()
    cohort_id = f"c-{roster_id[:16]}"
    dataset = paths.cohort_dataset_file(cohort_id)
    dataset.parent.mkdir(parents=True, exist_ok=True)
    dataset.write_bytes(("dataset" + suffix).encode())
    return catalog.register_cohort(
        cohort_id=cohort_id,
        name="sample" + suffix,
        description="Example cohort",
        origin_kind="file_import",
        origin_details={"source": "fixture", "ordinal": 1},
        roster_id=roster_id,
        row_count=2,
        distinct_cik_count=2,
        dataset_sha256=file_sha256(dataset),
        dataset_path=paths.relative_path(dataset),
        tags=("test", "sample"),
    )


def test_catalog_schema_uses_hardened_wal_connections(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)

    assert paths.catalog_file.is_file()
    with sqlite3.connect(paths.catalog_file) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    with catalog._connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert connection.execute("PRAGMA page_size").fetchone()[0] == 8192


def test_register_persists_relative_path_and_canonical_manifest(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths)

    assert record.dataset_path == f"{record.cohort_id}/ciks.parquet"
    assert not Path(record.dataset_path).is_absolute()
    assert catalog.get_cohort("sample") == record
    manifest_path = paths.cohort_manifest_file(record.cohort_id)
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert manifest_text == json.dumps(
        record.to_manifest(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    assert json.loads(manifest_text)["origin"] == {"ordinal": 1, "source": "fixture"}


def test_registration_refuses_digest_mismatch(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    roster_id = hashlib.sha256(b"roster").hexdigest()
    cohort_id = f"c-{roster_id[:16]}"
    dataset = paths.cohort_dataset_file(cohort_id)
    dataset.parent.mkdir(parents=True)
    dataset.write_bytes(b"wrong")

    with pytest.raises(ValueError, match="digest"):
        catalog.register_cohort(
            cohort_id=cohort_id,
            origin_kind="file_import",
            roster_id=roster_id,
            row_count=1,
            distinct_cik_count=1,
            dataset_sha256="0" * 64,
            dataset_path=f"{cohort_id}/ciks.parquet",
        )


def test_official_source_identity_tracks_source_snapshot_not_cik_set(
    tmp_path: Path,
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    roster_id = hashlib.sha256(b"same-cik-set").hexdigest()
    source_ids = (
        hashlib.sha256(b"source-a").hexdigest(),
        hashlib.sha256(b"source-b").hexdigest(),
    )
    records = []
    for index, source_id in enumerate(source_ids):
        cohort_id = f"c-{source_id[:16]}"
        dataset = paths.cohort_dataset_file(cohort_id)
        dataset.parent.mkdir(parents=True)
        dataset.write_text(f"source {index}", encoding="utf-8")
        records.append(
            catalog.register_cohort(
                cohort_id=cohort_id,
                origin_kind="official_source",
                origin_details={"source_snapshot_id": source_id},
                roster_id=roster_id,
                row_count=1,
                distinct_cik_count=1,
                dataset_sha256=file_sha256(dataset),
                dataset_path=paths.relative_path(dataset),
            )
        )

    assert records[0].roster_id == records[1].roster_id == roster_id
    assert records[0].cohort_id != records[1].cohort_id


def test_official_source_requires_a_snapshot_identity(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    with pytest.raises(ValueError, match="source_snapshot_id"):
        catalog.register_cohort(
            cohort_id="c-" + "0" * 16,
            origin_kind="official_source",
            roster_id=hashlib.sha256(b"roster").hexdigest(),
            row_count=0,
            distinct_cik_count=0,
            dataset_sha256="0" * 64,
            dataset_path="c-0000000000000000/ciks.parquet",
        )


def test_collision_on_existing_short_id_is_refused(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths)
    colliding_roster = record.roster_id[:16] + "f" * 48
    with catalog._connection() as connection:
        connection.execute(
            "UPDATE cohorts SET roster_id = ? WHERE cohort_id = ?",
            (colliding_roster, record.cohort_id),
        )

    with pytest.raises(CohortCollisionError):
        catalog.register_cohort(
            cohort_id=record.cohort_id,
            origin_kind="file_import",
            roster_id=record.roster_id,
            row_count=2,
            distinct_cik_count=2,
            dataset_sha256=record.dataset_sha256,
            dataset_path=record.dataset_path,
        )


def test_catalog_lookup_tags_search_and_identifier_prefix(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths)

    assert catalog.resolve_cohort_identifier(record.cohort_id[2:9]) == record
    assert catalog.list_cohorts(tag="test", pinned_only=False, search="Example") == [
        record
    ]
    catalog.add_tags(record.cohort_id, ("active",))
    catalog.remove_tags(record.cohort_id, ("test",))
    updated = catalog.get_cohort(record.cohort_id)
    assert updated is not None and updated.tags == ("active", "sample")
    manifest_path = paths.cohort_manifest_file(record.cohort_id)
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["tags"] == [
        "active",
        "sample",
    ]
    catalog.rename_cohort(record.cohort_id, "renamed")
    assert catalog.get_cohort("renamed") is not None
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["name"] == "renamed"


def test_identifier_short_missing_and_ambiguous_refusal(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    shared = "abcdef0"
    one = _registered(catalog, paths, suffix="-one", roster_id=shared + "1" * 57)
    _registered(catalog, paths, suffix="-two", roster_id=shared + "2" * 57)
    with pytest.raises(CohortIdentifierError, match="short"):
        catalog.resolve_cohort_identifier("123")
    with pytest.raises(CohortIdentifierError, match="Ambiguous"):
        catalog.resolve_cohort_identifier(shared)
    with pytest.raises(CohortIdentifierError, match="not found"):
        catalog.resolve_cohort_identifier("1234567")


def test_active_source_pointer_and_pinned_deletion_guards(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    active = _registered(catalog, paths, suffix="-active")
    catalog.set_active_source_pointer("cik_lookup", active.cohort_id)
    assert catalog.get_active_source_pointer("cik_lookup") == active.cohort_id
    with pytest.raises(CohortActiveSourceError):
        catalog.delete_cohort(active.cohort_id)

    pinned = _registered(catalog, paths, suffix="-pinned")
    with catalog._connection() as connection:
        connection.execute(
            "UPDATE cohorts SET pinned = 1 WHERE cohort_id = ?", (pinned.cohort_id,)
        )
    with pytest.raises(CohortPinnedError):
        catalog.delete_cohort(pinned.cohort_id)


def test_alias_reference_requires_force_and_force_removes_alias(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths)
    with catalog._connection() as connection:
        connection.execute(
            "CREATE TABLE object_session_aliases (session_id TEXT, alias_name TEXT, target_id TEXT)"
        )
        connection.execute(
            "INSERT INTO object_session_aliases VALUES (?, ?, ?)",
            ("default", "A", record.cohort_id),
        )
    with pytest.raises(CohortInUseError):
        catalog.delete_cohort(record.cohort_id)

    assert catalog.delete_cohort(record.cohort_id, force=True)
    assert catalog.get_cohort(record.cohort_id) is None
    assert not paths.cohort_dir(record.cohort_id).exists()
    with sqlite3.connect(paths.catalog_file) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM object_session_aliases WHERE target_id = ?",
                (record.cohort_id,),
            ).fetchone()[0]
            == 0
        )


def test_delete_purge_stays_inside_cohorts_root(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths)
    outside = tmp_path / "outside"
    outside.mkdir()
    cohort_dir = paths.cohort_dir(record.cohort_id)
    cohort_dir.rename(tmp_path / "saved-cohort")
    cohort_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes root"):
        catalog.delete_cohort(record.cohort_id)
    assert catalog.get_cohort(record.cohort_id) == record


def test_failed_catalog_insert_removes_published_directory(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    roster_id = hashlib.sha256(b"failure").hexdigest()
    cohort_id = f"c-{roster_id[:16]}"
    dataset = paths.cohort_dataset_file(cohort_id)
    dataset.parent.mkdir(parents=True)
    dataset.write_bytes(b"dataset")
    with catalog._connection() as connection:
        connection.execute(
            "CREATE TRIGGER reject_cohort BEFORE INSERT ON cohorts BEGIN SELECT RAISE(ABORT, 'rejected'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="rejected"):
        catalog.register_cohort(
            cohort_id=cohort_id,
            origin_kind="file_import",
            roster_id=roster_id,
            row_count=1,
            distinct_cik_count=1,
            dataset_sha256=file_sha256(dataset),
            dataset_path=f"{cohort_id}/ciks.parquet",
        )
    assert not paths.cohort_dir(cohort_id).exists()


def test_cleanup_removes_only_stale_stage_directories(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    stale = paths.create_staging_dir("c-0123456789abcdef")
    fresh = paths.create_staging_dir("c-fedcba9876543210")
    os.utime(stale, (1, 1))

    assert catalog.cleanup_stale_staging(max_age_seconds=60) == 1
    assert not stale.exists()
    assert fresh.exists()


def test_stale_purge_stage_restores_cohort_still_in_catalog(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths)
    final_dir = paths.cohort_dir(record.cohort_id)
    stage = paths.cohorts_root / f".stage-purge-{record.cohort_id}-{'a' * 32}"
    final_dir.rename(stage)
    os.utime(stage, (1, 1))

    assert catalog.cleanup_stale_staging(max_age_seconds=0) == 0
    assert final_dir.is_dir()
    assert not stage.exists()
