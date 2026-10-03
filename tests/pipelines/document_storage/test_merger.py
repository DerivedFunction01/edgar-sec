"""Tests for chunk merging and snapshot publication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.domain.identity import Cik
from edgar_sec.pipelines.document_storage.checkpoint import write_chunk_snapshot
from edgar_sec.pipelines.document_storage.merger import (
    MergeError,
    current_snapshot_artifact,
    publish_snapshot,
    read_pointer,
    validate_chunks,
)
from edgar_sec.pipelines.document_storage.paths import (
    SNAPSHOT_ARTIFACT_NAME,
    chunk_checkpoint_path,
)

ACCESSION = "0001234567-11-000001"


def _write_chunk(path: Path, rows: list[tuple[str, str, str]]) -> None:
    occurrences = []
    raw = {}
    texts = {}
    statuses = {}
    for accession, document_path, status in rows:
        key = DocumentLocator.from_parts(accession, document_path).document_locator_key
        occurrence = FilingOccurrence(
            occurrence_id=f"occ-{key[:8]}",
            source_cik=Cik.from_raw("1234567"),
            accession=DocumentLocator.from_parts(accession, document_path).accession,
            document_path=document_path,
            form="10-K",
            filing_date="2012-02-15",
            report_date=None,
            doc_id=key,
        )
        occurrences.append(occurrence)
        raw[key] = f"payload {document_path}".encode()
        texts[occurrence.occurrence_id] = f"text {document_path}"
        statuses[occurrence.occurrence_id] = status
    write_chunk_snapshot(path, occurrences, raw, texts, statuses, {})


def _seed_chunks(chunks_dir: Path) -> None:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    _write_chunk(
        chunk_checkpoint_path(chunks_dir, "c1"),
        [(ACCESSION, "a.htm", "ok"), (ACCESSION, "b.htm", "ok")],
    )
    _write_chunk(
        chunk_checkpoint_path(chunks_dir, "c2"),
        [(ACCESSION, "c.htm", "ok"), (ACCESSION, "d.htm", "missing")],
    )


def test_publish_merges_and_points_current(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    _seed_chunks(chunks_dir)

    result = publish_snapshot(
        run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots
    )
    assert result.run_id == "run-1"
    assert result.snapshot.row_count == 4
    assert result.snapshot.chunk_count == 2
    assert result.snapshot.artifact_path.is_file()
    assert result.snapshot.artifact_path.name == SNAPSHOT_ARTIFACT_NAME
    assert result.reused is False

    pointer = read_pointer(snapshots)
    assert pointer is not None
    assert pointer["snapshot_id"] == result.snapshot.snapshot_id
    assert pointer["run_id"] == "run-1"
    assert current_snapshot_artifact(snapshots) == result.snapshot.artifact_path


def test_manifest_records_the_run(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    _seed_chunks(chunks_dir)
    result = publish_snapshot(
        run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots
    )
    manifest = json.loads(
        (result.snapshot.artifact_path.parent / "manifest.json").read_text()
    )
    assert manifest["run_id"] == "run-1"
    assert manifest["row_count"] == 4
    assert manifest["dataset"] == "document_storage"
    assert manifest["missing_documents"] == 1
    assert len(manifest["logical_fingerprint"]) == 64
    assert len(manifest["chunks"]) == 2


def test_the_content_fingerprint_identifies_content_not_file_bytes(
    tmp_path: Path,
) -> None:
    """Merged Parquet bytes vary, so identity comes from the chunk inputs."""
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    _seed_chunks(chunks_dir)
    first = publish_snapshot(
        run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots
    )
    manifest_a = json.loads(
        (first.snapshot.artifact_path.parent / "manifest.json").read_text()
    )
    second = publish_snapshot(
        run_id="run-2", chunks_dir=chunks_dir, snapshots_root=snapshots
    )
    manifest_b = json.loads(
        (second.snapshot.artifact_path.parent / "manifest.json").read_text()
    )
    assert manifest_a["logical_fingerprint"] == manifest_b["logical_fingerprint"]
    assert len(manifest_a["artifact_file_sha256"]) == 64
    assert manifest_a["artifact_file_sha256"] != str(
        first.snapshot.artifact_path.stat().st_size
    )


def test_the_content_fingerprint_changes_with_content(tmp_path: Path) -> None:
    first_chunks = tmp_path / "first"
    second_chunks = tmp_path / "second"
    _seed_chunks(first_chunks)
    second_chunks.mkdir(parents=True, exist_ok=True)
    _write_chunk(
        chunk_checkpoint_path(second_chunks, "c1"),
        [(ACCESSION, "c.htm", "ok")],
    )
    snapshots = tmp_path / "snapshots"
    first = publish_snapshot(
        run_id="run-1", chunks_dir=first_chunks, snapshots_root=snapshots
    )
    second = publish_snapshot(
        run_id="run-2", chunks_dir=second_chunks, snapshots_root=snapshots
    )
    assert _fingerprint(first) != _fingerprint(second)


def _fingerprint(result: object) -> str:
    manifest = json.loads(
        (result.snapshot.artifact_path.parent / "manifest.json").read_text()
    )
    return str(manifest["logical_fingerprint"])


def test_snapshots_are_immutable(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    _seed_chunks(chunks_dir)
    publish_snapshot(run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots)
    with pytest.raises(MergeError, match="already exists"):
        publish_snapshot(
            run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots
        )


def test_no_chunks_refuses_to_publish(tmp_path: Path) -> None:
    empty = tmp_path / "chunks"
    empty.mkdir()
    with pytest.raises(MergeError, match="no chunk checkpoints"):
        publish_snapshot(
            run_id="run-1", chunks_dir=empty, snapshots_root=tmp_path / "snapshots"
        )


def test_all_chunks_invalid_refuses_to_publish(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    chunks_dir.mkdir()
    chunk_checkpoint_path(chunks_dir, "c1").write_bytes(b"garbage")
    with pytest.raises(MergeError, match="no usable chunk"):
        publish_snapshot(
            run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots
        )


def test_one_bad_chunk_publishes_the_rest_with_a_warning(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    _seed_chunks(chunks_dir)
    chunk_checkpoint_path(chunks_dir, "broken").write_bytes(b"garbage")

    result = publish_snapshot(
        run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots
    )
    assert result.snapshot.row_count == 4
    assert result.snapshot.chunk_count == 2
    assert any("broken" in warning for warning in result.warnings)


def test_pointer_is_written_after_the_artifact(tmp_path: Path) -> None:
    """A pointer must never name a snapshot that does not exist."""
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    _seed_chunks(chunks_dir)
    result = publish_snapshot(
        run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots
    )
    pointer = read_pointer(snapshots)
    assert pointer is not None
    assert (snapshots / pointer["snapshot_id"] / SNAPSHOT_ARTIFACT_NAME).is_file()
    assert result.snapshot.artifact_path.is_file()


def test_no_staging_directory_is_left_behind(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    _seed_chunks(chunks_dir)
    publish_snapshot(run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots)
    assert not [p for p in snapshots.iterdir() if p.name.startswith(".staging-")]


def test_explicit_snapshot_id_is_used(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    _seed_chunks(chunks_dir)
    result = publish_snapshot(
        run_id="run-1",
        chunks_dir=chunks_dir,
        snapshots_root=snapshots,
        snapshot_id="snap-explicit",
    )
    assert result.snapshot.snapshot_id == "snap-explicit"
    assert read_pointer(snapshots)["snapshot_id"] == "snap-explicit"


def test_derived_snapshot_id_is_stable(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    for root in (first, second):
        _seed_chunks(root / "chunks")
        publish_snapshot(
            run_id="run-same",
            chunks_dir=root / "chunks",
            snapshots_root=root / "snapshots",
        )
    assert (
        read_pointer(first / "snapshots")["snapshot_id"]
        == (read_pointer(second / "snapshots")["snapshot_id"])
    )


# --- pointer readers ------------------------------------------------------


def test_absent_pointer_reads_as_none(tmp_path: Path) -> None:
    assert read_pointer(tmp_path) is None
    assert current_snapshot_artifact(tmp_path) is None


def test_pointer_to_a_deleted_snapshot_reads_as_absent(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    snapshots = tmp_path / "snapshots"
    _seed_chunks(chunks_dir)
    result = publish_snapshot(
        run_id="run-1", chunks_dir=chunks_dir, snapshots_root=snapshots
    )
    import shutil

    shutil.rmtree(result.snapshot.artifact_path.parent)
    assert read_pointer(snapshots) is not None
    assert current_snapshot_artifact(snapshots) is None


# --- chunk validation -----------------------------------------------------


def test_validate_chunks_reports_each_problem(tmp_path: Path) -> None:
    good = chunk_checkpoint_path(tmp_path, "good")
    _write_chunk(good, [(ACCESSION, "a.htm", "ok")])
    chunk_checkpoint_path(tmp_path, "broken").write_bytes(b"garbage")

    usable, warnings = validate_chunks(
        [good, chunk_checkpoint_path(tmp_path, "broken"), tmp_path / "absent.parquet"]
    )
    assert usable == [good]
    assert len(warnings) == 2
    assert any("broken" in warning for warning in warnings)
    assert any("absent" in warning for warning in warnings)
