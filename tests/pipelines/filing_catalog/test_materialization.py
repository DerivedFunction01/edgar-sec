"""Unit tests for the filing-catalog materialization SQL."""

from __future__ import annotations

import duckdb
import pytest

from edgar_sec.domain.filing_catalog.schemas import TARGET_COLUMNS
from edgar_sec.infra.storage.duckdb import copy_query_to_parquet
from edgar_sec.pipelines.filing_catalog.materialization import (
    build_part_unnest_query,
    build_profile_query,
)


def test_build_profile_query_rejects_unsafe_identifier() -> None:
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        build_profile_query("source; DROP TABLE source")


def test_unnest_query_embeds_the_path_as_a_literal() -> None:
    query = build_part_unnest_query("data/part-00000.parquet")
    assert "read_parquet('data/part-00000.parquet')" in query
    for column in TARGET_COLUMNS:
        assert column in query


def test_unnest_query_takes_exactly_one_source_part() -> None:
    """Peak memory stays proportional to a part rather than to the cohort."""
    query = build_part_unnest_query("data/part-00007.parquet")
    assert "read_parquet('data/part-00007.parquet')" in query
    assert "read_parquet([" not in query


def test_unnest_query_does_not_correlate_the_unnest() -> None:
    """A DELIM_SCAN pins every nested value before emitting, and does not spill."""
    query = build_part_unnest_query("data/part-00000.parquet")
    assert "LATERAL" not in query
    assert "UNNEST(filings)" in query
    assert "UNNEST(t.filings)" not in query


def test_unnest_query_deduplicates_within_its_own_part() -> None:
    """Occurrence dedup is per part, which is only sound under the CIK guard."""
    query = build_part_unnest_query("p.parquet")
    assert "PARTITION BY sha256(" in query
    assert "occurrence_rank = 1" in query


def test_unnest_query_escapes_a_path_rather_than_concatenating_it() -> None:
    query = build_part_unnest_query("data/it's.parquet")
    assert "it''s.parquet" in query
    assert "read_parquet('data/it's.parquet')" not in query


def test_unnest_query_refuses_an_empty_part_path() -> None:
    with pytest.raises(ValueError, match="requires a source part"):
        build_part_unnest_query("")


def test_unnest_query_applies_the_documented_derivation_rules() -> None:
    query = build_part_unnest_query("p.parquet")
    assert "replace(accession_number, '-', '')" in query
    assert "accession_number || '.txt'" in query
    assert "ltrim(source_cik, '0')" in query
    assert query.count("sha256(") >= 3
    # occurrences are unique even when a registrant is re-fetched
    assert "occurrence_rank" in query
    assert "ORDER BY source_cik, accession, document_path" in query


def test_unnest_query_normalizes_whitespace_primary_documents() -> None:
    """The engine strips before comparing, and the SQL must align."""
    query = build_part_unnest_query("p.parquet")
    assert "nullif(trim(primary_document), '')" in query


def test_unnest_query_executes_without_a_delim_join(tmp_path, sample_source) -> None:
    """Only a real plan proves DuckDB stopped inserting the delim scan itself."""
    con = duckdb.connect()
    try:
        query = build_part_unnest_query(str(sample_source))
        plan = "\n".join(
            str(row[-1]) for row in con.execute(f"EXPLAIN {query}").fetchall()
        )
        assert "DELIM_SCAN" not in plan
        assert "DELIM_JOIN" not in plan

        destination = tmp_path / "targets.parquet"
        rows = copy_query_to_parquet(con, query, destination)
        assert rows > 0
    finally:
        con.close()


def test_profile_query_dedups_on_latest_fetched_at() -> None:
    query = build_profile_query("source")
    assert "PARTITION BY cik" in query
    assert "ORDER BY fetched_at DESC NULLS LAST" in query
    assert "WHERE rn = 1" in query
    assert "ORDER BY cik" in query
