import json

from conftest import imp

from defs.storage import file_sha256

application = imp("phases.01_metadata_extraction.core.application")
checkpoints = imp("phases.01_metadata_extraction.core.checkpoints")
chunks_mod = imp("phases.01_metadata_extraction.core.chunks")
merge_mod = imp("phases.01_metadata_extraction.core.merge")
normalize = imp("phases.01_metadata_extraction.core.normalize")
schemas = imp("phases.01_metadata_extraction.core.schemas")

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def make_row(cik, name="TEST CO", status="ok", chunk_id=1, accession_suffix="000001"):
    row = normalize.normalize_submissions(
        {
            "cik": cik,
            "name": name,
            "filings": {
                "recent": {
                    "accessionNumber": [f"{cik}-21-{accession_suffix}"],
                    "filingDate": ["2021-01-01"],
                    "reportDate": ["2020-12-31"],
                    "acceptanceDateTime": ["2021-01-01T10:00:00.000Z"],
                    "act": ["34"],
                    "form": ["10-K"],
                    "fileNumber": ["000-1"],
                    "filmNumber": ["1"],
                    "items": ["10-K"],
                    "core_type": [None],
                    "size": [1000],
                    "isXBRL": [1],
                    "isInlineXBRL": [1],
                    "isXBRLNumeric": [0],
                    "primaryDocument": ["a.htm"],
                    "primaryDocDescription": ["10-K"],
                },
                "files": [],
            },
        },
        cik_padded=cik,
        input_name=name,
        snapshot_id="s1",
        fetched_at="2026-08-27T00:00:00Z",
        source_url=f"https://data.sec.gov/submissions/CIK{cik}.json",
        byte_count=10,
        historical_payloads=[],
        historical_errors=[],
    )
    row["chunk_id"] = chunk_id
    row["input_fingerprint"] = "fp"
    row["status"] = status
    return row


def test_merge_partition_report_describes_finalized_artifact(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021", "0000000022"]
    )
    report = merge_mod.merge_partition(str(artifacts), 1)
    assert report.partition_id == 1
    assert report.row_count == 3
    assert report.filing_record_count == 3
    assert report.errors == []
    assert report.duplicate_accessions == []
    assert report.report_source == "finalized_partition_artifact"
    artifact = (
        artifacts
        / "partitions"
        / "partition-00001"
        / "merge"
        / "submission_metadata.parquet"
    )
    assert report.output_path == str(artifact.resolve())
    assert artifact.exists()
    stored = json.loads(
        (
            artifacts / "partitions" / "partition-00001" / "merge" / "merge_report.json"
        ).read_text()
    )
    assert stored["report_source"] == "finalized_partition_artifact"
    table = pq.read_table(str(artifact), schema=schemas.SUBMISSION_METADATA_SCHEMA)
    assert sorted(table.column("cik").to_pylist()) == [
        "0000000020",
        "0000000021",
        "0000000022",
    ]


def test_merge_partition_rejects_missing_chunk(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021", "0000000022"]
    )
    for name in (artifacts / "partitions" / "partition-00001" / "chunks").iterdir():
        if "chunk-00002" in name.name:
            name.unlink()
    with pytest.raises(merge_mod.MergeError, match="incomplete"):
        merge_mod.merge_partition(str(artifacts), 1)


def test_merge_partition_rejects_mixed_versions(tmp_path):
    artifacts, _plan = build_partitioned_run(tmp_path, ["0000000020", "0000000021"])
    chunks_dir = artifacts / "partitions" / "partition-00001" / "chunks"
    files = sorted(chunks_dir.iterdir())
    table = pq.read_table(str(files[0]), schema=schemas.SUBMISSION_METADATA_SCHEMA)
    versions = ["0.0.9"] * table.num_rows
    table = table.set_column(
        table.schema.get_field_index("schema_version"),
        "schema_version",
        pa.array(versions, type=pa.string()),
    )
    pq.write_table(table, str(files[0]))
    with pytest.raises(merge_mod.MergeError):
        merge_mod.merge_partition(str(artifacts), 1)


def test_merge_partition_rejects_chunk_files_outside_plan(tmp_path):
    artifacts, _plan = build_partitioned_run(tmp_path, ["0000000020", "0000000021"])
    chunks_dir = artifacts / "partitions" / "partition-00001" / "chunks"
    files = sorted(chunks_dir.iterdir())
    table = pq.read_table(str(files[0]), schema=schemas.SUBMISSION_METADATA_SCHEMA)
    pq.write_table(
        table,
        str(
            chunks_dir / "submission_metadata-v1.0.0-chunk-00009-000001-000001.parquet"
        ),
    )
    with pytest.raises(merge_mod.MergeError, match="outside the plan"):
        merge_mod.merge_partition(str(artifacts), 1)


def test_merge_partition_reports_duplicate_accessions_without_rejecting(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021"], chunk_size=1
    )
    chunks_dir = artifacts / "partitions" / "partition-00001" / "chunks"
    for path in sorted(chunks_dir.iterdir()):
        table = pq.read_table(str(path), schema=schemas.SUBMISSION_METADATA_SCHEMA)
        filings = table.column("filings").to_pylist()
        for record in filings[0]:
            if record:
                record["accession_number"] = "0000000020-21-000001"
                record["accession_number_normalized"] = "000000002021000001"
        table = table.set_column(
            table.schema.get_field_index("filings"),
            "filings",
            pa.array(
                filings, type=schemas.SUBMISSION_METADATA_SCHEMA.field("filings").type
            ),
        )
        pq.write_table(table, str(path))
    report = merge_mod.merge_partition(str(artifacts), 1)
    assert report.duplicate_accessions == ["000000002021000001"]
    assert report.warnings
    assert report.report_source == "finalized_partition_artifact"


def test_merge_partition_rejects_wrong_input_fingerprint(tmp_path):
    artifacts, plan = build_partitioned_run(tmp_path, ["0000000020", "0000000021"])
    plan["input_fingerprint"] = "different"
    (artifacts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(merge_mod.MergeError, match="fingerprint"):
        merge_mod.merge_partition(str(artifacts), 1)


def test_merge_partition_rejects_jsonl_output(tmp_path):
    artifacts, _plan = build_partitioned_run(tmp_path, ["0000000020", "0000000021"])
    with pytest.raises(merge_mod.MergeError, match="Parquet"):
        merge_mod.merge_partition(str(artifacts), 1, output_storage_format="jsonl")


def build_partitioned_run(tmp_path, ciks, chunk_size=2, partition_count=1):
    """Write a partitioned plan plus completed partitions under partitions/."""
    artifacts = tmp_path / "run"
    artifacts.mkdir()
    ordered = sorted(ciks)
    ranges = chunks_mod.assign_chunks(ordered, chunk_size)
    partitions = chunks_mod.assign_partitions(ordered, partition_count, chunk_size)
    plan = {
        "schema_version": schemas.SCHEMA_VERSION,
        "input_fingerprint": "fp",
        "row_count": len(ordered),
        "cik_padded": ordered,
        "chunks": [rng.to_dict() for rng in ranges],
        "partitions": [p.to_dict() for p in partitions],
        "partition_count": partition_count,
        "plan_hash": "x",
    }
    (artifacts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    for partition in partitions:
        part_dir = (
            artifacts
            / "partitions"
            / f"partition-{partition.partition_id:05d}"
            / "chunks"
        )
        part_dir.mkdir(parents=True)
        for rng in partition.chunks:
            rows = [
                make_row(cik, chunk_id=rng.chunk_id)
                for cik in partition.cik_padded[rng.start_row : rng.end_row + 1]
            ]
            checkpoints.write_checkpoint(
                rows,
                str(
                    part_dir
                    / checkpoints.chunk_filename(
                        rng.chunk_id, rng.start_row, rng.end_row
                    )
                ),
            )
    return artifacts, plan


def test_merge_final_combines_partition_artifacts_without_chunks(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021", "0000000022"], partition_count=2
    )
    merge_mod.merge_partition(str(artifacts), 1)
    merge_mod.merge_partition(str(artifacts), 2)
    # Remove raw chunk directories to prove the final merge only reads artifacts.
    for pid in (1, 2):
        part_chunks = artifacts / "partitions" / f"partition-{pid:05d}" / "chunks"
        for path in list(part_chunks.iterdir()):
            path.unlink()
        (
            artifacts
            / "partitions"
            / f"partition-{pid:05d}"
            / "merge"
            / "merge_report.json"
        ).unlink()
    output = tmp_path / "final.parquet"
    report = merge_mod.merge_partition_artifacts(str(artifacts), str(output))
    assert report.row_count == 3
    assert report.report_source == "finalized_artifact"
    assert output.exists()
    final_report = json.loads((artifacts / "merge" / "merge_report.json").read_text())
    assert final_report["report_source"] == "finalized_artifact"
    for pid in (1, 2):
        partition_report = (
            artifacts
            / "partitions"
            / f"partition-{pid:05d}"
            / "merge"
            / "merge_report.json"
        )
        assert json.loads(partition_report.read_text())["report_source"] == (
            "finalized_partition_artifact"
        )


def test_merge_final_rejects_missing_partition_artifact(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021"], partition_count=2
    )
    merge_mod.merge_partition(str(artifacts), 1)
    with pytest.raises(merge_mod.MergeError, match="missing partition"):
        merge_mod.merge_partition_artifacts(
            str(artifacts), str(tmp_path / "out.parquet")
        )


def test_merge_partition_rejects_unknown_partition(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021"], partition_count=1
    )
    with pytest.raises(merge_mod.MergeError, match="not present"):
        merge_mod.merge_partition(str(artifacts), 9)


def test_merge_partition_emits_progress_events(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021", "0000000022"], partition_count=1
    )
    events = []
    report = merge_mod.merge_partition(str(artifacts), 1, progress=events.append)
    assert report.row_count == 3
    stages = [event["stage"] for event in events if event["type"] == "merge_stage"]
    assert stages == ["validate", "publish"]
    assert all(event["rows"] == 3 for event in events if event["type"] == "merge_stage")
    readbacks = [event for event in events if event["type"] == "readback_done"]
    assert len(readbacks) == 1
    assert readbacks[0]["rows"] == 3


def test_merge_final_emits_progress_events(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021"], partition_count=2
    )
    merge_mod.merge_partition(str(artifacts), 1)
    merge_mod.merge_partition(str(artifacts), 2)
    events = []
    report = merge_mod.merge_partition_artifacts(
        str(artifacts), str(tmp_path / "out.parquet"), progress=events.append
    )
    assert report.row_count == 2
    validated = [event for event in events if event["type"] == "partition_validated"]
    assert {event["partition_id"] for event in validated} == {1, 2}
    assert sum(event["rows"] for event in validated) == 2
    assert [event for event in events if event["type"] == "readback_done"]


def test_merge_results_are_deterministic(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021", "0000000022"], partition_count=2
    )
    merge_mod.merge_partition(str(artifacts), 1)
    merge_mod.merge_partition(str(artifacts), 2)
    first = merge_mod.merge_partition_artifacts(
        str(artifacts), str(tmp_path / "run1.parquet")
    ).to_dict()
    second = merge_mod.merge_partition_artifacts(
        str(artifacts), str(tmp_path / "run2.parquet")
    ).to_dict()
    assert first["row_count"] == second["row_count"]
    assert first["filing_record_count"] == second["filing_record_count"]
    assert first["input_fingerprint"] == second["input_fingerprint"]
    assert (tmp_path / "run1.parquet").exists()
    assert (tmp_path / "run2.parquet").exists()


def test_merge_survives_failing_progress_callback(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021"], partition_count=1
    )

    def bad_callback(event):
        raise RuntimeError("callback exploded")

    report = merge_mod.merge_partition(str(artifacts), 1, progress=bad_callback)
    assert report.row_count == 2


def test_merge_final_rejects_foreign_partition_artifact(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021"], partition_count=1
    )
    merge_mod.merge_partition(str(artifacts), 1)
    # Corrupt the artifact's fingerprint so it no longer matches the plan.
    artifact = (
        artifacts
        / "partitions"
        / "partition-00001"
        / "merge"
        / "submission_metadata.parquet"
    )
    table = pq.read_table(str(artifact), schema=schemas.SUBMISSION_METADATA_SCHEMA)
    new_rows = [{**row, "input_fingerprint": "other"} for row in table.to_pylist()]
    pq.write_table(
        pa.Table.from_pylist(new_rows, schema=schemas.SUBMISSION_METADATA_SCHEMA),
        str(artifact),
    )
    with pytest.raises(merge_mod.MergeError, match="sha256"):
        merge_mod.merge_partition_artifacts(
            str(artifacts), str(tmp_path / "out.parquet")
        )


def test_merge_final_rejects_tampered_partition_artifact(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021"], partition_count=1
    )
    merge_mod.merge_partition(str(artifacts), 1)
    artifact = (
        artifacts
        / "partitions"
        / "partition-00001"
        / "merge"
        / "submission_metadata.parquet"
    )
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(merge_mod.MergeError, match="sha256"):
        merge_mod.merge_partition_artifacts(
            str(artifacts), str(tmp_path / "out.parquet")
        )


def test_merge_final_rejects_stale_plan_partition_artifact(tmp_path):
    artifacts, plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021"], partition_count=1
    )
    merge_mod.merge_partition(str(artifacts), 1)
    plan["plan_hash"] = "stale"
    (artifacts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(merge_mod.MergeError, match="different plan"):
        merge_mod.merge_partition_artifacts(
            str(artifacts), str(tmp_path / "out.parquet")
        )


def test_merge_final_carries_duplicate_accessions_from_reports(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021"], partition_count=2
    )
    merge_mod.merge_partition(str(artifacts), 1)
    merge_mod.merge_partition(str(artifacts), 2)
    report_path = (
        artifacts / "partitions" / "partition-00001" / "merge" / "merge_report.json"
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["duplicate_accessions"] = ["000000002021000001"]
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    report = merge_mod.merge_partition_artifacts(
        str(artifacts), str(tmp_path / "out.parquet")
    )
    assert report.duplicate_accessions == ["000000002021000001"]
    assert report.warnings


def test_merge_final_single_partition_copies_artifact_bytes(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021", "0000000022"], partition_count=1
    )
    part_report = merge_mod.merge_partition(str(artifacts), 1)
    output = tmp_path / "final.parquet"
    report = merge_mod.merge_partition_artifacts(str(artifacts), str(output))
    # Single-partition fast path: the final artifact is the same bytes.
    assert report.artifact_sha256 == part_report.artifact_sha256
    assert file_sha256(str(output)) == part_report.artifact_sha256
    assert report.row_count == 3
    assert not output.with_name("final.parquet.tmp").exists()


def test_merge_final_requires_partition_artifacts(tmp_path):
    artifacts, plan = build_partitioned_run(tmp_path, ["0000000020", "0000000021"])
    # A run whose plan carries no partition definitions has no finalized
    # partition artifacts; the final merge must fail instead of reading chunks.
    del plan["partitions"]
    (artifacts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(merge_mod.MergeError, match="partitioned plan"):
        merge_mod.merge_partition_artifacts(
            str(artifacts), str(tmp_path / "out.parquet")
        )


def test_merge_final_rejects_partial_partition_coverage(tmp_path):
    artifacts, _plan = build_partitioned_run(
        tmp_path, ["0000000020", "0000000021", "0000000022"], partition_count=2
    )
    merge_mod.merge_partition(str(artifacts), 1)
    merge_mod.merge_partition(str(artifacts), 2)
    # Drop one partition artifact; the remaining set no longer covers the plan.
    (
        artifacts
        / "partitions"
        / "partition-00002"
        / "merge"
        / "submission_metadata.parquet"
    ).unlink()
    with pytest.raises(merge_mod.MergeError):
        merge_mod.merge_partition_artifacts(
            str(artifacts), str(tmp_path / "out.parquet")
        )
