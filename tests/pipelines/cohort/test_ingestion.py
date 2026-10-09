import fcntl
import hashlib
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.pipelines.cohort.ingestion import (
    ingest_file_to_cohort,
    publish_derived_cohort,
)
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from tests.support import fixture_path


def test_ingests_csv_and_tracks_rejected_and_duplicate_rows(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)

    result = ingest_file_to_cohort(
        fixture_path("cik_sec_mini.csv"), catalog=catalog, paths=paths
    )

    assert result.quality.total_raw_rows == 8
    assert result.quality.usable_rows == 4
    assert result.quality.rejected_rows == 3
    assert result.quality.duplicate_rows == 1
    assert result.cohort.row_count == 4
    dataset = paths.resolve_relative_path(result.cohort.dataset_path)
    assert pq.read_table(dataset).to_pylist() == [
        {"ordinal": 0, "cik_padded": "0000000020", "name": "K Tron International Inc"},
        {"ordinal": 1, "cik_padded": "0000001761", "name": "Tranzonic Companies"},
        {"ordinal": 2, "cik_padded": "0000001985", "name": "Accel International Corp"},
        {"ordinal": 3, "cik_padded": "0000037996", "name": "FORD MOTOR CO"},
    ]
    assert result.cohort.dataset_sha256 == file_sha256(dataset)


def test_txt_defaults_names_and_deduplicates(tmp_path: Path) -> None:
    source = tmp_path / "registrants.txt"
    source.write_text("20\nnot-a-cik\n20\n1761\n", encoding="utf-8")
    paths = CohortPaths(tmp_path / "artifacts")
    result = ingest_file_to_cohort(source, catalog=CohortCatalog(paths), paths=paths)

    assert result.quality.total_raw_rows == 4
    assert result.quality.usable_rows == 2
    assert result.quality.rejected_rows == 1
    assert result.quality.duplicate_rows == 1
    rows = pq.read_table(
        paths.resolve_relative_path(result.cohort.dataset_path)
    ).to_pylist()
    assert [row["name"] for row in rows] == ["", ""]


def test_tsv_pipe_and_headerless_inputs_are_supported(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path / "artifacts")
    catalog = CohortCatalog(paths)
    tsv = tmp_path / "registrants.tsv"
    tsv.write_text("CIK\tEntity Name\n20\tBeta\n10\tAlpha\n", encoding="utf-8")
    pipe = tmp_path / "headerless.csv"
    pipe.write_text("30|Gamma\n40|Delta\n", encoding="utf-8")

    tsv_result = ingest_file_to_cohort(tsv, catalog=catalog, paths=paths)
    pipe_result = ingest_file_to_cohort(pipe, catalog=catalog, paths=paths)

    tsv_rows = pq.read_table(
        paths.resolve_relative_path(tsv_result.cohort.dataset_path)
    ).to_pylist()
    pipe_rows = pq.read_table(
        paths.resolve_relative_path(pipe_result.cohort.dataset_path)
    ).to_pylist()
    assert [row["name"] for row in tsv_rows] == ["Alpha", "Beta"]
    assert [row["cik_padded"] for row in pipe_rows] == ["0000000030", "0000000040"]
    assert [row["name"] for row in pipe_rows] == ["Gamma", "Delta"]


def test_missing_names_and_conflicting_duplicates_are_canonical(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path / "artifacts")
    catalog = CohortCatalog(paths)
    no_names = tmp_path / "ciks.csv"
    no_names.write_text("CIK\n30\n", encoding="utf-8")
    unrelated_column = tmp_path / "ciks_with_status.csv"
    unrelated_column.write_text("CIK,Status\n40,Active\n", encoding="utf-8")
    parquet_without_name = tmp_path / "ciks_without_name.parquet"
    pq.write_table(pa.table({"cik": [50]}), parquet_without_name)
    conflicting = tmp_path / "duplicate_names.csv"
    conflicting.write_text(
        "cik,name\n20,  \n20,Zed Corp\n20,Alpha Corp\n", encoding="utf-8"
    )

    missing_result = ingest_file_to_cohort(no_names, catalog=catalog, paths=paths)
    unrelated_result = ingest_file_to_cohort(
        unrelated_column, catalog=catalog, paths=paths
    )
    parquet_result = ingest_file_to_cohort(
        parquet_without_name, catalog=catalog, paths=paths
    )
    duplicate_result = ingest_file_to_cohort(conflicting, catalog=catalog, paths=paths)

    missing_rows = pq.read_table(
        paths.resolve_relative_path(missing_result.cohort.dataset_path)
    ).to_pylist()
    unrelated_rows = pq.read_table(
        paths.resolve_relative_path(unrelated_result.cohort.dataset_path)
    ).to_pylist()
    parquet_rows = pq.read_table(
        paths.resolve_relative_path(parquet_result.cohort.dataset_path)
    ).to_pylist()
    duplicate_rows = pq.read_table(
        paths.resolve_relative_path(duplicate_result.cohort.dataset_path)
    ).to_pylist()
    assert missing_rows[0]["name"] == ""
    assert unrelated_rows[0]["name"] == ""
    assert parquet_rows[0]["name"] == ""
    assert duplicate_rows == [
        {"ordinal": 0, "cik_padded": "0000000020", "name": "Zed Corp"}
    ]


def test_parquet_ingestion_and_limit(tmp_path: Path) -> None:
    source = tmp_path / "input.parquet"
    pq.write_table(
        pa.table({"central_index_key": ["20", "10", "10"], "title": ["B", "A", "Z"]}),
        source,
    )
    paths = CohortPaths(tmp_path / "artifacts")
    result = ingest_file_to_cohort(
        source, catalog=CohortCatalog(paths), paths=paths, limit=2
    )

    assert result.quality.total_raw_rows == 2
    assert result.quality.usable_rows == 2
    assert result.quality.duplicate_rows == 0
    rows = pq.read_table(
        paths.resolve_relative_path(result.cohort.dataset_path)
    ).to_pylist()
    assert [row["name"] for row in rows] == ["A", "B"]


def test_roster_hash_uses_sorted_unique_padded_ciks(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("20\n10\n20\n", encoding="utf-8")
    paths = CohortPaths(tmp_path / "artifacts")
    result = ingest_file_to_cohort(source, catalog=CohortCatalog(paths), paths=paths)

    expected = hashlib.sha256(b"0000000010\n0000000020").hexdigest()
    assert result.cohort.roster_id == expected


def test_publish_derived_cohort_records_origin(tmp_path: Path) -> None:
    source = tmp_path / "sample.csv"
    source.write_text("cik,name\n20,Alpha\n10,Beta\n", encoding="utf-8")
    paths = CohortPaths(tmp_path / "artifacts")
    result = publish_derived_cohort(
        source,
        catalog=CohortCatalog(paths),
        paths=paths,
        origin_kind="sample",
        origin_details={"source_cohort_id": "c-source"},
        tags=("sample",),
    )

    assert result.cohort.origin_kind == "sample"
    assert '"source_cohort_id":"c-source"' in result.cohort.origin_json


def test_publish_derived_cohort_rejects_other_origins(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="sample or set_operation"):
        publish_derived_cohort(
            tmp_path / "missing.csv",
            catalog=CohortCatalog(paths),
            paths=paths,
            origin_kind="file_import",
        )


def test_publication_lock_covers_rename_and_catalog_insert(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "input.txt"
    source.write_text("20\n", encoding="utf-8")
    paths = CohortPaths(tmp_path / "artifacts")
    catalog = CohortCatalog(paths)
    register = catalog.register_cohort

    def register_under_publication_lock(**kwargs):
        descriptor = os.open(paths.cohorts_root / ".publication.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        final_dir = paths.cohort_dir(kwargs["cohort_id"])
        assert final_dir.is_dir()
        assert not (final_dir / ".stage.lease").exists()
        return register(**kwargs)

    monkeypatch.setattr(catalog, "register_cohort", register_under_publication_lock)

    result = ingest_file_to_cohort(source, catalog=catalog, paths=paths)

    assert catalog.get_cohort(result.cohort.cohort_id) == result.cohort
