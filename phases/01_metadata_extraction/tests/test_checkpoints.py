import pyarrow.parquet as pq
from conftest import imp

checkpoints = imp("phases.01_metadata_extraction.core.checkpoints")
schemas = imp("phases.01_metadata_extraction.core.schemas")
normalize = imp("phases.01_metadata_extraction.core.normalize")

import pytest


def make_row(cik="0000000020", status="ok", chunk_id=1):
    row = normalize.normalize_submissions(
        {
            "cik": cik,
            "name": "TEST CO",
            "filings": {
                "recent": {
                    "accessionNumber": [f"{cik[-10:]}-21-000001"],
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
        input_name="TEST",
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


def test_write_checkpoint_is_atomic_and_valid(tmp_path):
    final = tmp_path / "chunks" / checkpoints.chunk_filename(1, 0, 1)
    info = checkpoints.write_checkpoint(
        [make_row(), make_row("0000000021")], str(final)
    )
    assert info["rows"] == 2
    assert final.exists()
    assert not final.with_suffix(".parquet.tmp").exists()
    table = pq.read_table(str(final))
    assert table.num_rows == 2


def test_failed_rows_are_terminal_checkpoint_rows(tmp_path):
    final = tmp_path / "chunks" / checkpoints.chunk_filename(2, 0, 0)
    row = make_row()
    row["status"] = "failed"
    row["error"] = "status 404"
    info = checkpoints.write_checkpoint([row], str(final))
    assert info["rows"] == 1
    table = pq.read_table(str(final), schema=schemas.SUBMISSION_METADATA_SCHEMA)
    assert table.column("status").to_pylist() == ["failed"]
    assert table.column("error").to_pylist() == ["status 404"]


def test_schema_mismatch_is_rejected_on_load(tmp_path):
    final = tmp_path / "chunks" / checkpoints.chunk_filename(1, 0, 0)
    checkpoints.write_checkpoint([make_row()], str(final))
    with pytest.raises(ValueError):
        checkpoints.load_checkpoint(str(final), expected_version="0.0.1")


def test_find_chunk_checkpoint_skips_tmp_partials(tmp_path):
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    (
        chunks_dir / "submission_metadata-v1.0.0-chunk-00001-000000-000001.parquet.tmp"
    ).write_bytes(b"partial")
    assert checkpoints.find_chunk_checkpoint(str(chunks_dir), 1) is None
    final = chunks_dir / checkpoints.chunk_filename(1, 0, 1)
    checkpoints.write_checkpoint([make_row(), make_row("0000000021")], str(final))
    found = checkpoints.find_chunk_checkpoint(str(chunks_dir), 1, "1.0.0")
    assert found == str(final)


def test_find_chunk_checkpoint_ignores_other_versions(tmp_path):
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    # a file whose name declares an old version must not satisfy the request
    (
        chunks_dir / "submission_metadata-v0.9.0-chunk-00001-000000-000000.parquet"
    ).write_bytes(b"garbage")
    assert checkpoints.find_chunk_checkpoint(str(chunks_dir), 1, "1.0.0") is None


def test_filename_encodes_version_chunk_and_range():
    name = checkpoints.chunk_filename(12, 11000, 11999)
    assert name == "submission_metadata-v1.0.0-chunk-00012-011000-011999.parquet"
    parsed = checkpoints.parse_chunk_filename(name)
    assert parsed["chunk_id"] == 12
    assert parsed["start_row"] == 11000
    assert parsed["end_row"] == 11999
    assert parsed["version"] == "1.0.0"
