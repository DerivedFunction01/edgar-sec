from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.infra.storage.parquet import StagedParquetWriter
from edgar_sec.pipelines.document_inventory.checkpoint import (
    OUTCOME_SCHEMA,
    STATUS_FETCH_FAILED,
    STATUS_PARSED,
)
from edgar_sec.pipelines.document_inventory.snapshot.anti_join import (
    anti_join,
    build_staging,
)


def _outcome(accession: str, status: str = STATUS_PARSED) -> dict:
    return {"accession": accession, "status": status}


def _entry(accession: str) -> dict:
    return {"accession": accession, "entry_id": f"entry-{accession}"}


def _source(accession: str, cik: str, plan: str = "plan-a") -> dict:
    return {"accession": accession, "source_cik": cik, "first_seen_by": plan}


def _write(path: Path, rows: list[dict], schema: pa.Schema) -> None:
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def test_anti_join_keeps_relations_in_duckdb_and_writes_parquet(tmp_path: Path) -> None:
    accession_a = "000000000126000001"
    accession_b = "000000000226000001"
    staged = build_staging(
        tmp_path / "stage",
        outcome_rows=[_outcome(accession_a), _outcome(accession_b)],
        entry_rows=[_entry(accession_a), _entry(accession_b)],
        source_rows=[
            _source(accession_a, "0000000001"),
            _source(accession_a, "0000000003"),
            _source(accession_b, "0000000002"),
        ],
        batch_rows=1,
    )
    current_accessions = tmp_path / "current_accessions.parquet"
    current_sources = tmp_path / "current_sources.parquet"
    _write(
        current_accessions,
        [{"accession": accession_a}],
        pa.schema([("accession", pa.string())]),
    )
    _write(
        current_sources,
        [{"accession": accession_a, "source_cik": "0000000001"}],
        pa.schema([("accession", pa.string()), ("source_cik", pa.string())]),
    )

    result = anti_join(
        staged,
        current_accessions,
        current_sources,
        tmp_path / "results",
        temp_directory=tmp_path / "duckdb-temp",
    )

    assert (result.new_accession_count, result.known_accession_count) == (1, 1)
    assert result.candidate_entry_count == 1
    assert result.new_source_count == 2
    assert pq.read_table(result.new_accessions_path).column(
        "accession"
    ).to_pylist() == [accession_b]
    assert pq.read_table(result.candidate_entries_path).column(
        "accession"
    ).to_pylist() == [accession_b]
    edges = (
        pq.read_table(result.new_sources_path)
        .select(["accession", "source_cik"])
        .to_pylist()
    )
    assert {(r["accession"], r["source_cik"]) for r in edges} == {
        (accession_a, "0000000003"),
        (accession_b, "0000000002"),
    }


def test_staging_consumes_iterables_in_bounded_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes = []
    original = StagedParquetWriter.write_batch

    def observe(self, batch):
        sizes.append(
            batch.num_rows
            if isinstance(batch, pa.RecordBatch)
            else len(batch["accession"])
        )
        return original(self, batch)

    monkeypatch.setattr(StagedParquetWriter, "write_batch", observe)
    rows = (_outcome(f"{number:010d}26000001") for number in range(1, 19))
    staged = build_staging(
        tmp_path / "stage",
        outcome_rows=rows,
        entry_rows=iter(()),
        source_rows=iter(()),
        batch_rows=5,
    )
    assert pq.read_metadata(staged.outcomes_path).num_rows == 18
    assert max(sizes) <= 5
    assert len(sizes) >= 4


def test_anti_join_refuses_worker_failures(tmp_path: Path) -> None:
    staged = build_staging(
        tmp_path / "stage",
        outcome_rows=[_outcome("000000000126000001", STATUS_FETCH_FAILED)],
        entry_rows=[],
        source_rows=[],
    )
    with pytest.raises(ValueError, match="refusing snapshot outcome"):
        anti_join(staged, None, None, tmp_path / "results")


def test_explicit_refresh_keeps_known_accession_entries(tmp_path: Path) -> None:
    accession = "000000000126000001"
    staged = build_staging(
        tmp_path / "stage",
        outcome_rows=[_outcome(accession)],
        entry_rows=[_entry(accession)],
        source_rows=[],
    )
    current_accessions = tmp_path / "current_accessions.parquet"
    _write(
        current_accessions,
        [{"accession": accession}],
        pa.schema([("accession", pa.string())]),
    )

    result = anti_join(
        staged,
        current_accessions,
        None,
        tmp_path / "results",
        explicit_refresh=True,
    )

    assert result.new_accession_count == 0
    assert result.known_accession_count == 1
    assert result.candidate_entry_count == 1
