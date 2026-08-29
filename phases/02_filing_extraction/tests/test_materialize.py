from __future__ import annotations

import importlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from defs.storage import StorageError

schemas = importlib.import_module("phases.01_metadata_extraction.core.schemas")
materializer = importlib.import_module("phases.02_filing_extraction.core.materialize")


def row(cik: str, accession: str = "0000000001-24-000001") -> dict:
    return {
        "cik": cik,
        "snapshot_id": "s",
        "fetched_at": "2024-01-01T00:00:00Z",
        "source_url": "u",
        "response_sha256": "h",
        "byte_count": 1,
        "schema_version": schemas.SCHEMA_VERSION,
        "status": "ok",
        "error": None,
        "anomalies": [],
        "extra_fields": None,
        "identity": {"name": "Co", "former_names": []},
        "classification": {
            "entity_type": None,
            "sic_code": None,
            "sic_description": None,
            "owner_org": None,
            "filer_category": None,
        },
        "identifiers": {"ein": None, "lei": None},
        "contact": {
            "phone": None,
            "website": None,
            "investor_website": None,
            "description": None,
        },
        "incorporation": {"state": None, "state_description": None},
        "reporting": {"fiscal_year_end": None},
        "insider_transactions": {"owner_exists": None, "issuer_exists": None},
        "addresses": {"mailing": None, "business": None},
        "listings": [],
        "filings": [
            {
                "accession_number": accession,
                "accession_number_normalized": accession,
                "filing_date": "2024-02-01",
                "report_date": "2023-12-31",
                "acceptance_datetime": None,
                "act": None,
                "form": "10-K",
                "file_number": None,
                "film_number": None,
                "items": [],
                "core_type": None,
                "size": 3,
                "is_xbrl": False,
                "is_inline_xbrl": False,
                "is_xbrl_numeric": False,
                "primary_document": "a.htm",
                "primary_doc_description": "Annual",
                "archive_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/a.htm",
                "source_section": "recent",
                "source_file": "source",
                "source_array_index": 0,
            }
        ],
        "submission_files": [],
        "input_name": "n",
        "input_fingerprint": "fp",
        "chunk_id": 0,
        "historical_files_total": 0,
        "historical_files_failed": 0,
        "historical_records_total": 0,
    }


def test_materialize_reads_only_finalized_artifact(tmp_path):
    source = tmp_path / "submission_metadata.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [row("0000000001")], schema=schemas.SUBMISSION_METADATA_SCHEMA
        ),
        source,
    )
    (tmp_path / "merge_report.json").write_text("{}", encoding="utf-8")
    materializer.materialize(str(source), str(tmp_path / "catalogs"))
    target = (
        tmp_path
        / "manifests"
        / "filing_extraction"
        / "filing_targets"
        / "final"
        / "form=10-K"
        / "data.parquet"
    )
    assert pq.read_table(target).column("accession").to_pylist() == [
        "000000000124000001"
    ]
    assert pq.read_table(
        tmp_path
        / "manifests"
        / "filing_extraction"
        / "company_profiles"
        / "final"
        / "company_profiles.parquet"
    ).column_names == list(materializer.PROFILE_COLUMNS)


def test_chunks_are_rejected(tmp_path):
    path = tmp_path / "chunks" / "submission_metadata.parquet"
    path.parent.mkdir()
    with pytest.raises(StorageError, match="finalized artifact"):
        materializer.materialize(str(path), str(tmp_path / "catalogs"))
