"""Offline contracts for temporal normalized-document snapshots."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest

from defs.sql import insert_values, make_sql_executor

schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
snapshot = importlib.import_module("phases.025_webpage_storage.core.snapshot")
snapshot_merge = importlib.import_module(
    "phases.025_webpage_storage.core.snapshot_merge"
)
partition_handoff = importlib.import_module(
    "phases.025_webpage_storage.core.partition_handoff"
)
cli = importlib.import_module("phases.025_webpage_storage.cli")
vacuum = importlib.import_module("phases.025_webpage_storage.core.vacuum")


def _partition(
    path: Path,
    rows: list[tuple[dict, bytes | None]],
    *,
    stored_hash_override: str | None = None,
) -> Path:
    path.touch()
    executor = make_sql_executor(path, dialect="sqlite")
    schemas.create_partition_schema(executor)
    for occurrence, payload in rows:
        doc = occurrence["doc_id"]
        executor.exec(
            executor.compiler.compile(
                insert_values(schemas.FILING_OCCURRENCES_TABLE, occurrence)
            )
        )
        if payload is not None:
            executor.exec(
                executor.compiler.compile(
                    insert_values(
                        schemas.DOCUMENT_BLOBS_TABLE,
                        {
                            "doc_id": doc,
                            "accession": occurrence["accession"],
                            "document_path": occurrence["document_path"],
                            "byte_size": len(payload),
                            "mime_type": "text/html",
                            "raw_payload_sha256": hashlib.sha256(payload).hexdigest(),
                        },
                    )
                )
            )
            executor.exec(
                executor.compiler.compile(
                    insert_values(
                        schemas.NORMALIZED_DOCUMENTS_TABLE,
                        {
                            "normalized_artifact_id": f"normalized-{doc[:8]}",
                            "source_doc_id": doc,
                            "byte_size": len(payload),
                            "normalized_payload": schemas.compress_payload(payload),
                            "payload_sha256": stored_hash_override
                            or hashlib.sha256(payload).hexdigest(),
                            "mime_type": "text/html",
                            "representation": "clean_text",
                            "processor_fingerprint": "fixture:v1",
                            "schema_version": schemas.NORMALIZED_SCHEMA_VERSION,
                            "processor_metadata": "{}",
                        },
                    )
                )
            )
    executor.backend.connection.commit()
    executor.close()
    return path


def _occurrence(cik: str, accession: str, document_path: str, occurrence: str):
    return {
        "occurrence_id": occurrence,
        "source_cik": cik,
        "accession": accession,
        "document_path": document_path,
        "form": "10-K",
        "filing_date": "2023-01-02",
        "report_date": "2022-12-31",
        "doc_id": schemas.doc_id(accession, document_path),
    }


def test_index_payload_split_and_reader(tmp_path: Path):
    partition = _partition(
        tmp_path / "partition-00001.sqlite",
        [(_occurrence("0001", "acc-1", "doc.htm", "occ-1"), b"normalized text")],
    )
    manifest = snapshot.publish_projected_snapshot([partition], artifacts_root=tmp_path)
    reader = snapshot.SnapshotReader(tmp_path, manifest["snapshot_id"])
    rows = reader.index_rows(form="10-K")
    assert set(rows[0]) == set(snapshot.INDEX_COLUMNS)
    assert rows[0]["payload_file"].endswith("payload-00001.parquet")
    assert reader.payload_rows(rows) == [
        {"doc_id": rows[0]["doc_id"], "clean_text": "normalized text"}
    ]


def test_bounded_materialization_emits_stage_progress(tmp_path: Path):
    partition = _partition(
        tmp_path / "partition-00001.sqlite",
        [
            (_occurrence("0001", "acc-1", "doc.htm", "occ-1"), b"one"),
            (_occurrence("0002", "acc-2", "doc.htm", "occ-2"), b"two"),
        ],
    )
    events: list[dict] = []
    manifest = snapshot.publish_projected_snapshot(
        [partition],
        artifacts_root=tmp_path,
        batch_size=1,
        target_bytes=1,
        progress=events.append,
    )
    assert manifest["snapshot_id"]
    types = [event["type"] for event in events]
    assert types.count("partition_done") == 1
    assert types.count("part_written") == 2
    assert types.count("quarter_done") == 1
    assert events[-1]["type"] == "publish_manifest"

    vacuum_events: list[dict] = []
    compacted = vacuum.vacuum_snapshots(
        artifacts_root=tmp_path,
        snapshot_ids=[manifest["snapshot_id"]],
        workers=1,
        batch_size=1,
        target_bytes=1,
        progress=vacuum_events.append,
    )
    assert compacted["snapshot_id"]
    assert any(event["type"] == "vacuum_sources_resolved" for event in vacuum_events)
    assert vacuum_events[-1]["type"] == "publish_manifest"


def test_publication_layout_is_independent_of_batch_size(tmp_path: Path):
    rows = [
        (
            _occurrence(f"{index:04d}", f"acc-{index}", "doc.htm", f"occ-{index}"),
            f"payload text {index}".encode(),
        )
        for index in range(1, 6)
    ]
    partition = _partition(tmp_path / "partition-00001.sqlite", rows)

    tight = tmp_path / "tight"
    loose = tmp_path / "loose"
    tight_manifest = snapshot.publish_projected_snapshot(
        [partition], artifacts_root=tight, batch_size=1, target_bytes=1 << 30
    )
    loose_manifest = snapshot.publish_projected_snapshot(
        [partition], artifacts_root=loose, batch_size=4096, target_bytes=1 << 30
    )
    assert tight_manifest["snapshot_id"] == loose_manifest["snapshot_id"]

    def _layout(root: Path, manifest_id: str) -> list[tuple[str, int]]:
        snapshot_dir = (
            root
            / "manifests"
            / "webpage_storage"
            / "normalized_documents"
            / "snapshots"
            / manifest_id
        )
        payload_parts = sorted(p.name for p in snapshot_dir.rglob("payload-*.parquet"))
        index_parts = sorted(p.name for p in snapshot_dir.rglob("index-*.parquet"))
        return [(name, 1) for name in payload_parts] + [
            (name, 1) for name in index_parts
        ]

    tight_layout = _layout(tight, tight_manifest["snapshot_id"])
    loose_layout = _layout(loose, loose_manifest["snapshot_id"])
    assert tight_layout == loose_layout
    assert len([name for name, _ in tight_layout if name.startswith("payload")]) == 1
    assert len([name for name, _ in tight_layout if name.startswith("index")]) == 1


def test_payload_parts_split_and_oversized_document_gets_own_part(tmp_path: Path):
    rows = [
        (_occurrence("0001", "acc-1", "doc.htm", "occ-1"), b"aaaaaa"),
        (_occurrence("0002", "acc-2", "doc.htm", "occ-2"), b"bbbbbb"),
        (_occurrence("0003", "acc-3", "doc.htm", "occ-3"), b"cccccc"),
        (
            _occurrence("0004", "acc-4", "doc.htm", "occ-4"),
            b"h" * 64,
        ),
    ]
    partition = _partition(tmp_path / "partition-00001.sqlite", rows)
    manifest = snapshot.publish_projected_snapshot(
        [partition], artifacts_root=tmp_path, target_bytes=16
    )
    payload_parts = [
        part for part in manifest["resolved_parts"] if part["kind"] == "payload"
    ]
    # Greedy packing in doc_id order: the 64-byte document always occupies a
    # single-row part; the three 6-byte documents pack two per part at most.
    assert sorted(part["row_count"] for part in payload_parts) == [1, 1, 2]


def test_payload_hash_mismatch_fails_before_publication(tmp_path: Path):
    partition = _partition(
        tmp_path / "partition-00001.sqlite",
        [(_occurrence("0001", "acc-1", "doc.htm", "occ-1"), b"content")],
        stored_hash_override="deadbeef",
    )
    with pytest.raises(ValueError, match="payload hash mismatch"):
        snapshot.publish_projected_snapshot([partition], artifacts_root=tmp_path)
    assert not (
        tmp_path
        / "manifests"
        / "webpage_storage"
        / "normalized_documents"
        / "current.json"
    ).exists()


def test_cli_imports_finalized_partition_handoff(tmp_path: Path, capsys):
    partition = _partition(
        tmp_path / "partition-00001.sqlite",
        [(_occurrence("0001", "acc-1", "doc.htm", "occ-1"), b"text")],
    )
    partition_handoff.write_handoff(
        partition,
        plan_id="plan-1",
        run_id="run-plan-1",
        partition_id=1,
        partition_count=1,
    )
    assert (
        cli.main(
            [
                "merge-to-snapshot",
                "--partition-db",
                str(partition),
                "--artifacts-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert "snapshot_id" in capsys.readouterr().out


def test_late_occurrence_reuses_inherited_payload(tmp_path: Path):
    first = _partition(
        tmp_path / "partition-00001.sqlite",
        [(_occurrence("0001", "acc-1", "doc.htm", "occ-1"), b"shared")],
    )
    first_manifest = snapshot.publish_projected_snapshot(
        [first], artifacts_root=tmp_path
    )
    late = _partition(
        tmp_path / "partition-00002.sqlite",
        [(_occurrence("0002", "acc-1", "doc.htm", "occ-2"), None)],
    )
    second_manifest = snapshot_merge.merge_partitions_to_snapshot(
        [late],
        artifacts_root=tmp_path,
        base_snapshot_id=first_manifest["snapshot_id"],
    )
    reader = snapshot.SnapshotReader(tmp_path, second_manifest["snapshot_id"])
    rows = reader.index_rows()
    assert {row["occurrence_id"] for row in rows} == {"occ-1", "occ-2"}
    assert len({row["payload_file"] for row in rows}) == 1
    assert len(reader.payload_rows(rows)) == 1


def test_parallel_vacuum_materializes_union(tmp_path: Path):
    first = _partition(
        tmp_path / "partition-00001.sqlite",
        [(_occurrence("0001", "acc-1", "doc.htm", "occ-1"), b"one")],
    )
    first_manifest = snapshot.publish_projected_snapshot(
        [first], artifacts_root=tmp_path
    )
    second = _partition(
        tmp_path / "partition-00002.sqlite",
        [(_occurrence("0002", "acc-2", "doc.htm", "occ-2"), b"two")],
    )
    second_manifest = snapshot_merge.merge_partitions_to_snapshot(
        [second],
        artifacts_root=tmp_path,
        base_snapshot_id=first_manifest["snapshot_id"],
    )
    vacuum_manifest = vacuum.vacuum_snapshots(
        artifacts_root=tmp_path,
        snapshot_ids=[first_manifest["snapshot_id"], second_manifest["snapshot_id"]],
        workers=2,
        target_bytes=1024,
    )
    reader = snapshot.SnapshotReader(tmp_path, vacuum_manifest["snapshot_id"])
    assert len(reader.index_rows()) == 2
    assert len(reader.payload_rows(reader.index_rows())) == 2
    assert vacuum_manifest["merged_from"] == sorted(
        [first_manifest["snapshot_id"], second_manifest["snapshot_id"]]
    )


def test_purge_requires_dependency_closure(tmp_path: Path):
    first = _partition(
        tmp_path / "partition-00001.sqlite",
        [(_occurrence("0001", "acc-1", "doc.htm", "occ-1"), b"one")],
    )
    first_manifest = snapshot.publish_projected_snapshot(
        [first], artifacts_root=tmp_path
    )
    late = _partition(
        tmp_path / "partition-00002.sqlite",
        [(_occurrence("0002", "acc-1", "doc.htm", "occ-2"), None)],
    )
    second_manifest = snapshot_merge.merge_partitions_to_snapshot(
        [late],
        artifacts_root=tmp_path,
        base_snapshot_id=first_manifest["snapshot_id"],
    )
    with pytest.raises(ValueError, match="referenced"):
        vacuum.vacuum_snapshots(
            artifacts_root=tmp_path,
            snapshot_ids=[first_manifest["snapshot_id"]],
            workers=2,
            purge_sources=True,
        )
    merged = vacuum.vacuum_snapshots(
        artifacts_root=tmp_path,
        snapshot_ids=[first_manifest["snapshot_id"]],
        workers=2,
        purge_dependency_closure=True,
    )
    assert set(merged["merged_from"]) == {
        first_manifest["snapshot_id"],
        second_manifest["snapshot_id"],
    }
