"""Run manifest identity pinning and deterministic chunk partitioning."""

from pathlib import Path

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.pipelines.document_inventory.paths import inventory_run_paths
from edgar_sec.pipelines.document_inventory.run_manifest import (
    ManifestMismatchError,
    OUTCOME_SCHEMA_VERSION,
    membership_digest,
    partition_into_chunks,
    read_run_manifest,
    validate_run_manifest,
    write_run_manifest,
)

IDENTITY = {
    "parent_snapshot_id": "snap-1",
    "canonical_cohort_id": "cohort-1",
    "source_identity": "source-1",
    "parser_version": "parser-1",
    "chunk_size": 2,
    "refresh_mode": "normal",
    "fetch_mode": "live",
}


def _items(count: int) -> list[IndexWorkItem]:
    result = []
    for n in range(1, count + 1):
        accession = AccessionNumber.from_any(f"{n:010d}26000001")
        result.append(
            IndexWorkItem(
                accession=accession,
                index_url=f"https://example.test/{accession.normalized}-index.htm",
            )
        )
    return result


def test_chunk_membership_ignores_input_arrival_order() -> None:
    items = _items(7)
    forward = partition_into_chunks(items, chunk_size=3)
    reverse = partition_into_chunks(list(reversed(items)), chunk_size=3)
    assert forward == reverse


def test_chunk_id_changes_with_work_order_version() -> None:
    items = _items(3)
    base = partition_into_chunks(items, chunk_size=3, work_order_version="1")[0][0]
    bumped = partition_into_chunks(items, chunk_size=3, work_order_version="2")[0][0]
    assert base != bumped


def test_membership_digest_is_order_independent() -> None:
    assert membership_digest(("a", "b", "c")) == membership_digest(("c", "a", "b"))


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    items = _items(5)
    written = write_run_manifest(paths, work_items=items, **IDENTITY)
    loaded = read_run_manifest(paths)
    assert loaded == written
    assert written.outcome_schema_version == OUTCOME_SCHEMA_VERSION
    assert len(written.chunk_identities) == 3


def test_manifest_excludes_machine_local_worker_count(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    written = write_run_manifest(paths, work_items=_items(2), **IDENTITY)
    assert "workers" not in written.settings_snapshot
    assert "runtime.workers" not in written.settings_snapshot
    assert "cache" not in written.settings_snapshot


def test_validate_accepts_identical_resume(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    items = _items(5)
    written = write_run_manifest(paths, work_items=items, **IDENTITY)
    again = validate_run_manifest(
        written, run_id=written.run_id, work_items=items, **IDENTITY
    )
    assert again == written


def test_validate_missing_manifest_refuses(tmp_path: Path) -> None:
    with pytest.raises(ManifestMismatchError):
        validate_run_manifest(None, run_id="run-1", work_items=_items(1), **IDENTITY)


@pytest.mark.parametrize(
    "override",
    [
        {"chunk_size": 3},
        {"parser_version": "parser-2"},
        {"parent_snapshot_id": "snap-2"},
        {"fetch_mode": "force_refresh"},
        {"work_order_version": "2"},
    ],
)
def test_validate_mismatched_identity_refuses(
    tmp_path: Path, override: dict[str, object]
) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    items = _items(5)
    written = write_run_manifest(paths, work_items=items, **IDENTITY)
    changed = {**IDENTITY, **override}
    with pytest.raises(ManifestMismatchError):
        validate_run_manifest(
            written, run_id=written.run_id, work_items=items, **changed
        )


def test_validate_changed_worklist_refuses(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    items = _items(5)
    written = write_run_manifest(paths, work_items=items, **IDENTITY)
    with pytest.raises(ManifestMismatchError):
        validate_run_manifest(
            written, run_id=written.run_id, work_items=items[:-1], **IDENTITY
        )


@pytest.mark.parametrize("bad_mode", ["turbo", ""])
def test_write_rejects_unknown_modes(tmp_path: Path, bad_mode: str) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    refresh = {**IDENTITY, "refresh_mode": bad_mode}
    with pytest.raises(ValueError):
        write_run_manifest(paths, work_items=_items(1), **refresh)


def test_write_rejects_unknown_fetch_mode(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    fetch = {**IDENTITY, "fetch_mode": "ftp"}
    with pytest.raises(ValueError):
        write_run_manifest(paths, work_items=_items(1), **fetch)
