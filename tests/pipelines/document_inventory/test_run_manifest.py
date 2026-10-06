"""Path-backed work-order identity pinning and chunk partitioning."""

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
    iter_work_order_chunks,
    write_run_manifest,
    write_work_order,
)
from edgar_sec.pipelines.document_inventory import run_manifest as manifest_module

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
    return [
        IndexWorkItem(
            AccessionNumber.from_any(f"{n:010d}26000001"),
            f"https://example.test/{n}-index.htm",
        )
        for n in range(1, count + 1)
    ]


def _write_order(paths, items: list[IndexWorkItem]) -> Path:
    output = paths.work_order_path()
    write_work_order(output, items, batch_rows=2)
    return output


def _write_manifest(paths, items: list[IndexWorkItem]):
    work_order = _write_order(paths, items)
    return write_run_manifest(
        paths,
        work_order_path=work_order,
        fixture_id=None,
        **IDENTITY,
    )


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
    written = _write_manifest(paths, _items(5))
    assert read_run_manifest(paths) == written
    assert written.outcome_schema_version == OUTCOME_SCHEMA_VERSION
    assert written.work_order_rows == 5
    assert len(written.work_order_digest) == 64


def test_manifest_excludes_machine_local_worker_count(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    written = _write_manifest(paths, _items(2))
    assert "workers" not in written.settings_snapshot
    assert "runtime.workers" not in written.settings_snapshot
    assert "cache" not in written.settings_snapshot


def test_validate_accepts_identical_resume(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    written = _write_manifest(paths, _items(5))
    again = validate_run_manifest(
        written,
        run_id=written.run_id,
        fixture_id=None,
        work_order_path=paths.work_order_path(),
        **IDENTITY,
    )
    assert again == written


def test_validate_missing_manifest_refuses(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    with pytest.raises(ManifestMismatchError):
        validate_run_manifest(
            None,
            run_id="run-1",
            fixture_id=None,
            work_order_path=paths.work_order_path(),
            **IDENTITY,
        )


@pytest.mark.parametrize(
    "override",
    [
        {"chunk_size": 3},
        {"parser_version": "parser-2"},
        {"parent_snapshot_id": "snap-2"},
        {"fetch_mode": "force_refresh"},
        {"work_order_version": "3"},
    ],
)
def test_validate_mismatched_identity_refuses(
    tmp_path: Path, override: dict[str, object]
) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    written = _write_manifest(paths, _items(5))
    changed = {**IDENTITY, **override}
    with pytest.raises(ManifestMismatchError):
        validate_run_manifest(
            written,
            run_id=written.run_id,
            fixture_id=None,
            work_order_path=paths.work_order_path(),
            **changed,
        )


def test_validate_changed_worklist_refuses(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    written = _write_manifest(paths, _items(5))
    _write_order(paths, _items(4))
    with pytest.raises(ManifestMismatchError):
        validate_run_manifest(
            written,
            run_id=written.run_id,
            fixture_id=None,
            work_order_path=paths.work_order_path(),
            **IDENTITY,
        )


def test_work_order_writer_and_chunk_reader_materialize_bounded_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    batch_sizes = []
    writer_type = manifest_module.StagedParquetWriter
    original_write = writer_type.write_batch

    def observe_batch(writer, batch):
        batch_sizes.append(len(batch["accession"]))
        return original_write(writer, batch)

    monkeypatch.setattr(writer_type, "write_batch", observe_batch)

    def items():
        for n in range(1, 65):
            accession = AccessionNumber.from_any(f"{n:010d}26000001")
            yield IndexWorkItem(accession, f"https://example.test/{n}")

    identity = write_work_order(paths.work_order_path(), items(), batch_rows=7)
    total = maximum_chunk = 0
    for _chunk, members in iter_work_order_chunks(
        paths.work_order_path(), chunk_size=9
    ):
        total += len(members)
        maximum_chunk = max(maximum_chunk, len(members))
    assert identity.row_count == total == 64
    assert maximum_chunk == 9
    assert max(batch_sizes) <= 7
    assert len(batch_sizes) > 1


@pytest.mark.parametrize("bad_mode", ["turbo", ""])
def test_write_rejects_unknown_modes(tmp_path: Path, bad_mode: str) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    _write_order(paths, _items(1))
    with pytest.raises(ValueError):
        write_run_manifest(
            paths,
            work_order_path=paths.work_order_path(),
            fixture_id=None,
            **{**IDENTITY, "refresh_mode": bad_mode},
        )


def test_write_rejects_unknown_fetch_mode(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "run-1")
    _write_order(paths, _items(1))
    with pytest.raises(ValueError):
        write_run_manifest(
            paths,
            work_order_path=paths.work_order_path(),
            fixture_id=None,
            **{**IDENTITY, "fetch_mode": "ftp"},
        )
