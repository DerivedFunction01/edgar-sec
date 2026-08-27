import json

from conftest import imp

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


def build_run(tmp_path, ciks, chunk_size=2):
    """Write plan.json plus one completed checkpoint per chunk."""
    artifacts = tmp_path / "run"
    artifacts.mkdir()
    ordered = sorted(ciks)
    ranges = chunks_mod.assign_chunks(ordered, chunk_size)
    plan = {
        "schema_version": schemas.SCHEMA_VERSION,
        "input_fingerprint": "fp",
        "row_count": len(ordered),
        "cik_padded": ordered,
        "chunks": [rng.to_dict() for rng in ranges],
        "plan_hash": "x",
    }
    (artifacts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    chunks_dir = artifacts / "chunks"
    chunks_dir.mkdir()
    for rng in ranges:
        rows = [make_row(cik, chunk_id=rng.chunk_id) for cik in ordered[rng.start_row : rng.end_row + 1]]
        checkpoints.write_checkpoint(rows, str(chunks_dir / checkpoints.chunk_filename(rng.chunk_id, rng.start_row, rng.end_row)))
    return artifacts, plan


def test_merge_writes_unified_dataset_and_report(tmp_path):
    artifacts, _plan = build_run(tmp_path, ["0000000020", "0000000021", "0000000022"])
    output = tmp_path / "merged" / "submission_metadata.parquet"
    report = merge_mod.merge_chunks(str(artifacts), str(output))
    assert report.row_count == 3
    assert report.filing_record_count == 3
    assert report.errors == []
    table = pq.read_table(str(output), schema=schemas.SUBMISSION_METADATA_SCHEMA)
    assert sorted(table.column("cik").to_pylist()) == ["0000000020", "0000000021", "0000000022"]
    assert (tmp_path / "run" / "merge" / "merge_report.json").exists()


def test_merge_rejects_missing_chunk(tmp_path):
    artifacts, _plan = build_run(tmp_path, ["0000000020", "0000000021", "0000000022"])
    # delete one chunk checkpoint
    for name in (artifacts / "chunks").iterdir():
        if "chunk-00002" in name.name:
            name.unlink()
    with pytest.raises(merge_mod.MergeError, match="incomplete"):
        merge_mod.merge_chunks(str(artifacts), str(tmp_path / "out.parquet"))


def test_merge_rejects_mixed_versions(tmp_path):
    artifacts, _plan = build_run(tmp_path, ["0000000020", "0000000021"])
    chunks_dir = artifacts / "chunks"
    # rewrite one chunk with a different schema_version value
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
        merge_mod.merge_chunks(str(artifacts), str(tmp_path / "out.parquet"))


def test_merge_rejects_duplicate_cik_rows(tmp_path):
    artifacts, _plan = build_run(tmp_path, ["0000000020", "0000000021"])
    chunks_dir = artifacts / "chunks"
    files = sorted(chunks_dir.iterdir())
    # duplicate a row into another chunk file with a fake range
    table = pq.read_table(str(files[0]), schema=schemas.SUBMISSION_METADATA_SCHEMA)
    pq.write_table(table, str(chunks_dir / "submission_metadata-v1.0.0-chunk-00009-000001-000001.parquet"))
    with pytest.raises(merge_mod.MergeError):
        merge_mod.merge_chunks(str(artifacts), str(tmp_path / "out.parquet"))


def test_merge_rejects_duplicate_accessions_across_ciks(tmp_path):
    artifacts, _plan = build_run(tmp_path, ["0000000020", "0000000021"], chunk_size=1)
    chunks_dir = artifacts / "chunks"
    files = sorted(chunks_dir.iterdir())
    # make both CIKs carry the same accession
    for index, path in enumerate(files):
        table = pq.read_table(str(path), schema=schemas.SUBMISSION_METADATA_SCHEMA)
        filings = table.column("filings").to_pylist()
        for record in filings[0]:
            if record:
                record["accession_number"] = "0000000020-21-000001"
                record["accession_number_normalized"] = "000000002021000001"
        table = table.set_column(
            table.schema.get_field_index("filings"),
            "filings",
            pa.array(filings, type=schemas.SUBMISSION_METADATA_SCHEMA.field("filings").type),
        )
        pq.write_table(table, str(path))
    with pytest.raises(merge_mod.MergeError, match="duplicate accession"):
        merge_mod.merge_chunks(str(artifacts), str(tmp_path / "out.parquet"))
    report = merge_mod.merge_chunks(
        str(artifacts), str(tmp_path / "out2.parquet"), allow_accession_duplicates=True
    )
    assert report.warnings


def test_merge_rejects_wrong_input_fingerprint(tmp_path):
    artifacts, plan = build_run(tmp_path, ["0000000020", "0000000021"])
    plan["input_fingerprint"] = "different"
    (artifacts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(merge_mod.MergeError, match="fingerprints"):
        merge_mod.merge_chunks(str(artifacts), str(tmp_path / "out.parquet"))


def test_merge_rejects_incomplete_row_counts(tmp_path):
    artifacts, _plan = build_run(tmp_path, ["0000000020", "0000000021", "0000000022"], chunk_size=3)
    chunks_dir = artifacts / "chunks"
    path = next(chunks_dir.iterdir())
    table = pq.read_table(str(path), schema=schemas.SUBMISSION_METADATA_SCHEMA)
    pq.write_table(table.slice(0, 1), str(path))
    with pytest.raises(merge_mod.MergeError, match="row count"):
        merge_mod.merge_chunks(str(artifacts), str(tmp_path / "out.parquet"))
