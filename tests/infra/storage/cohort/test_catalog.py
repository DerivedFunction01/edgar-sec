import fcntl
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
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
from edgar_sec.infra.storage.cohort.models import FamilyIndexRecord
from edgar_sec.infra.storage.cohort.paths import STAGING_LEASE_NAME


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


def _family_index(
    paths: CohortPaths, family_index_id: str, content: bytes = b"family index"
) -> tuple[Path, str]:
    dataset = paths.family_index_file(family_index_id)
    dataset.parent.mkdir(parents=True, exist_ok=True)
    dataset.write_bytes(content)
    return dataset, file_sha256(dataset)


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


def test_register_persists_relative_path_and_sqlite_metadata(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    record = _registered(catalog, paths)

    assert record.dataset_path == f"{record.cohort_id}/ciks.parquet"
    assert not Path(record.dataset_path).is_absolute()
    assert catalog.get_cohort("sample") == record
    assert record.manifest_schema_ver == "2.0.0"
    assert not hasattr(record, "to_manifest")
    assert not hasattr(catalog, "write_manifest")
    assert sorted(
        path.name for path in paths.cohort_dir(record.cohort_id).iterdir()
    ) == ["ciks.parquet"]
    with sqlite3.connect(paths.catalog_file) as connection:
        schema_version, origin_json = connection.execute(
            "SELECT manifest_schema_ver, origin_json FROM cohorts WHERE cohort_id = ?",
            (record.cohort_id,),
        ).fetchone()
    assert schema_version == record.manifest_schema_ver
    assert json.loads(origin_json) == {"ordinal": 1, "source": "fixture"}


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


def test_active_family_index_registration_and_lookup(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    cohort = _registered(catalog, paths)
    family_index_id = "a" * 32
    _, dataset_sha256 = _family_index(paths, family_index_id)
    rules_fingerprint = hashlib.sha256(b"rules").hexdigest()

    catalog.set_active_family_index(
        cohort.cohort_id, family_index_id, rules_fingerprint, dataset_sha256
    )

    record = catalog.get_active_family_index(cohort.cohort_id)
    assert record is not None
    assert isinstance(record, FamilyIndexRecord)
    assert record.universe_cohort_id == cohort.cohort_id
    assert record.family_index_id == family_index_id
    assert record.rules_fingerprint == rules_fingerprint
    assert record.dataset_path == (
        f"family_index/{family_index_id}/company_family.parquet"
    )
    assert record.dataset_sha256 == dataset_sha256
    assert record.pinned_at
    assert catalog.get_active_family_index("c-unknown") is None
    with sqlite3.connect(paths.catalog_file) as connection:
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(active_family_indices)"
        ).fetchall()
    assert any(
        row[2] == "cohorts" and row[3] == "universe_cohort_id" for row in foreign_keys
    )


def test_active_family_index_requires_existing_cohort(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    family_index_id = "b" * 32
    _, digest = _family_index(paths, family_index_id)

    with pytest.raises(CohortIdentifierError, match="Universe cohort not found"):
        catalog.set_active_family_index(
            "c-missing", family_index_id, hashlib.sha256(b"rules").hexdigest(), digest
        )


def test_active_family_index_requires_existing_dataset(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    cohort = _registered(catalog, paths)

    with pytest.raises(ValueError, match="dataset file is missing"):
        catalog.set_active_family_index(
            cohort.cohort_id,
            "c" * 32,
            hashlib.sha256(b"rules").hexdigest(),
            hashlib.sha256(b"dataset").hexdigest(),
        )


def test_active_family_index_rejects_digest_mismatch(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    cohort = _registered(catalog, paths)
    family_index_id = "d" * 32
    _family_index(paths, family_index_id)

    with pytest.raises(ValueError, match="digest does not match"):
        catalog.set_active_family_index(
            cohort.cohort_id,
            family_index_id,
            hashlib.sha256(b"rules").hexdigest(),
            "0" * 64,
        )


def test_active_family_index_replaces_pointer_for_same_universe(
    tmp_path: Path,
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    cohort = _registered(catalog, paths)
    first_id, second_id = "e" * 32, "f" * 32
    _, first_digest = _family_index(paths, first_id, b"first")
    _, second_digest = _family_index(paths, second_id, b"second")
    first_rules = hashlib.sha256(b"rules-1").hexdigest()
    second_rules = hashlib.sha256(b"rules-2").hexdigest()

    catalog.set_active_family_index(
        cohort.cohort_id, first_id, first_rules, first_digest
    )
    first_record = catalog.get_active_family_index(cohort.cohort_id)
    catalog.set_active_family_index(
        cohort.cohort_id, second_id, second_rules, second_digest
    )

    record = catalog.get_active_family_index(cohort.cohort_id)
    assert record is not None
    assert first_record is not None and first_record.family_index_id == first_id
    assert record.family_index_id != first_record.family_index_id
    assert record.family_index_id == second_id
    assert record.rules_fingerprint == second_rules
    assert record.dataset_sha256 == second_digest


@pytest.mark.parametrize(
    ("family_index_id", "rules_fingerprint", "dataset_sha256"),
    [
        ("A" * 32, "1" * 64, "2" * 64),
        ("a" * 32, "A" * 64, "2" * 64),
        ("a" * 32, "1" * 64, "g" * 64),
    ],
)
def test_active_family_index_requires_canonical_hex_values(
    tmp_path: Path,
    family_index_id: str,
    rules_fingerprint: str,
    dataset_sha256: str,
) -> None:
    catalog = CohortCatalog(CohortPaths(tmp_path))

    with pytest.raises(ValueError):
        catalog.set_active_family_index(
            "c-unknown", family_index_id, rules_fingerprint, dataset_sha256
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
    catalog.rename_cohort(record.cohort_id, "renamed")
    renamed = catalog.get_cohort("renamed")
    assert renamed is not None and renamed.name == "renamed"
    assert renamed.tags == ("active", "sample")
    assert not (paths.cohort_dir(record.cohort_id) / "cohort.json").exists()


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
    paths.refresh_staging_lease(stale, now=datetime.fromtimestamp(1, UTC))
    os.utime(stale, (1, 1))

    assert catalog.cleanup_stale_staging(max_age_seconds=60) == 1
    assert not stale.exists()
    assert fresh.exists()


def test_cleanup_keeps_old_stage_with_unexpired_lease(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    stage = paths.create_staging_dir("c-0123456789abcdef")
    os.utime(stage, (1, 1))

    assert catalog.cleanup_stale_staging(max_age_seconds=0) == 0
    assert catalog.cleanup_stale_staging(force=True) == 0
    assert stage.is_dir()


@pytest.mark.parametrize("lease_state", ["missing", "corrupt"])
def test_cleanup_quarantines_bad_lease_until_forced(
    tmp_path: Path, lease_state: str
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    stage = paths.create_staging_dir("c-0123456789abcdef")
    lease_path = stage / STAGING_LEASE_NAME
    if lease_state == "missing":
        lease_path.unlink()
    else:
        lease_path.write_text("not-json", encoding="utf-8")
    os.utime(stage, (datetime.now(UTC).timestamp() - 100,) * 2)

    assert catalog.cleanup_stale_staging(max_age_seconds=0) == 0
    quarantined = paths.list_staging_dirs()
    assert len(quarantined) == 1
    assert quarantined[0] != stage
    assert quarantined[0].name.startswith(".stage-quarantine-")
    assert catalog.cleanup_stale_staging(force=True) == 1
    assert not quarantined[0].exists()


def test_cleanup_removes_quarantined_stage_after_one_day(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    stage = paths.create_staging_dir("c-0123456789abcdef")
    (stage / STAGING_LEASE_NAME).unlink()
    os.utime(stage, (1, 1))

    assert catalog.cleanup_stale_staging(max_age_seconds=0) == 1
    assert paths.list_staging_dirs() == []


def test_cleanup_force_removes_fresh_stage_with_missing_lease(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    stage = paths.create_staging_dir("c-0123456789abcdef")
    (stage / STAGING_LEASE_NAME).unlink()

    assert catalog.cleanup_stale_staging(force=True) == 1
    assert not stage.exists()


def test_stale_cleanup_holds_publication_lock(tmp_path: Path, monkeypatch) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    stage = paths.create_staging_dir("c-0123456789abcdef")
    paths.refresh_staging_lease(stage, now=datetime.fromtimestamp(1, UTC))
    os.utime(stage, (1, 1))
    remove = CohortPaths.remove_staging_dir

    def check_locked(owner: CohortPaths, path: Path) -> None:
        descriptor = os.open(owner.cohorts_root / ".publication.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        remove(owner, path)

    monkeypatch.setattr(CohortPaths, "remove_staging_dir", check_locked)
    assert catalog.cleanup_stale_staging(max_age_seconds=0) == 1


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
