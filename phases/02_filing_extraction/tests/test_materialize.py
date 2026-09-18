from __future__ import annotations

import importlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from defs.filing_identity import document_locator_key, occurrence_id
from defs.storage import StorageError

schemas = importlib.import_module("phases.01_metadata_extraction.core.schemas")
materializer = importlib.import_module("phases.02_filing_extraction.core.materialize")


def row(cik: str, accession: str = "0000000001-24-000001", **filing_overrides) -> dict:
    filing = {
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
    filing.update(filing_overrides)
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
        "filings": [filing],
        "submission_files": [],
        "input_name": "n",
        "input_fingerprint": "fp",
        "chunk_id": 0,
        "historical_files_total": 0,
        "historical_files_failed": 0,
        "historical_records_total": 0,
    }


def _materialize_rows(tmp_path, rows: list[dict]) -> tuple[dict, pa.Table | None]:
    source = tmp_path / "submission_metadata.parquet"
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schemas.SUBMISSION_METADATA_SCHEMA),
        source,
    )
    (tmp_path / "merge_report.json").write_text("{}", encoding="utf-8")
    manifest = materializer.materialize(str(source), str(tmp_path / "catalogs"))
    target = (
        tmp_path
        / "manifests"
        / "filing_extraction"
        / "filing_targets"
        / "final"
        / "form=10-K"
        / "data.parquet"
    )
    return manifest, pq.read_table(target) if target.exists() else None


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


def test_ordinary_rows_carry_primary_document_provenance(tmp_path):
    _, table = _materialize_rows(tmp_path, [row("0000000001")])
    rows = table.to_pylist()
    assert rows[0]["document_path_source"] == "primary_document"
    assert rows[0]["document_path"] == "a.htm"
    assert rows[0]["archive_url"].endswith("/a.htm")


def test_fallback_rows_use_full_submission_bundle(tmp_path):
    accession = "0000950123-98-009115"
    _, table = _materialize_rows(
        tmp_path,
        [
            row(
                "0000020164",
                accession,
                primary_document="",
                archive_url=None,
                size=451189,
            )
        ],
    )
    rows = table.to_pylist()
    assert len(rows) == 1
    observed = rows[0]
    canonical = "000095012398009115"
    bundle_path = "0000950123-98-009115.txt"
    assert observed["document_path_source"] == "submission_bundle"
    assert observed["primary_document"] == ""
    assert observed["document_path"] == bundle_path
    assert observed["archive_url"] == (
        f"https://www.sec.gov/Archives/edgar/data/20164/{canonical}/{bundle_path}"
    )
    assert observed["occurrence_id"] == occurrence_id(
        "0000020164", canonical, bundle_path
    )
    assert observed["document_locator_key"] == document_locator_key(
        canonical, bundle_path
    )


def test_ciks_with_only_fallback_filings_appear_in_catalog(tmp_path):
    _, table = _materialize_rows(
        tmp_path,
        [
            row(
                "0000020164",
                "0000889697-98-000310",
                primary_document="",
                archive_url=None,
            )
        ],
    )
    rows = table.to_pylist()
    assert [r["source_cik"] for r in rows] == ["0000020164"]
    assert rows[0]["document_path"] == "0000889697-98-000310.txt"


def test_mixed_cik_keeps_both_filing_sources(tmp_path):
    _, table = _materialize_rows(
        tmp_path,
        [
            row(
                "0000000001",
                "0000000001-24-000001",
                primary_document="",
                archive_url=None,
            ),
            row("0000000001", "0000000001-24-000002"),
        ],
    )
    rows = {r["accession"]: r for r in table.to_pylist()}
    assert rows["000000000124000001"]["document_path_source"] == "submission_bundle"
    assert rows["000000000124000002"]["document_path_source"] == "primary_document"


def test_shared_accession_fans_out_occurrences_on_one_locator(tmp_path):
    _, table = _materialize_rows(
        tmp_path,
        [
            row(
                "0000000001",
                "0000000001-24-000001",
                primary_document="",
                archive_url=None,
            ),
            row(
                "0000000002",
                "0000000001-24-000001",
                primary_document="",
                archive_url=None,
            ),
        ],
    )
    rows = table.to_pylist()
    assert len({r["occurrence_id"] for r in rows}) == 2
    assert len({r["document_locator_key"] for r in rows}) == 1


def test_invalid_accession_and_missing_form_are_excluded_and_counted(tmp_path):
    manifest, table = _materialize_rows(
        tmp_path,
        [
            row("0000000001", "not-an-accession"),
            row("0000000002", "0000000001-24-000002", form=None),
        ],
    )
    assert table is None
    stats = manifest["document_path_sources"]
    assert stats["total_observations"] == 2
    assert stats["excluded_invalid_accession"] == 1
    assert stats["excluded_missing_form"] == 1
    assert stats["emitted_primary_document"] == 0
    assert stats["emitted_submission_bundle"] == 0


def test_catalog_identity_is_deterministic_and_policy_versioned(tmp_path):
    manifest, _ = _materialize_rows(tmp_path, [row("0000000001")])
    assert manifest["fallback_policy_version"] == (materializer.FALLBACK_POLICY_VERSION)
    # Deterministic: a second materialization of the same source rebuilds the
    # same catalog identity and artifact ids.
    source = tmp_path / "submission_metadata.parquet"
    (tmp_path / "merge_report.json").write_text("{}", encoding="utf-8")
    second = materializer.materialize(str(source), str(tmp_path / "catalogs"))
    assert second["catalog_id"] == manifest["catalog_id"]
    assert (
        second["artifact_ids"]["company_profiles"]
        == manifest["artifact_ids"]["company_profiles"]
    )
