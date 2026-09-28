"""Unit tests for the catalog SQL builders."""

from __future__ import annotations

import pytest

from edgar_sec.domain.filing_catalog.schemas import TARGET_COLUMNS
from edgar_sec.infra.storage.duckdb_catalog import (
    build_merged_targets_query,
    build_part_unnest_query,
    build_profile_query,
    sql_literal,
)


def test_sql_literal_escapes_embedded_quotes() -> None:
    assert sql_literal("a'b") == "'a''b'"
    assert sql_literal("plain") == "'plain'"


def test_sql_literal_cannot_be_escaped_out_of() -> None:
    """A hostile path must not be able to close the literal and append SQL."""
    hostile = "x.parquet' ; DROP TABLE source; --"
    literal = sql_literal(hostile)
    assert literal.count("'") % 2 == 0
    assert literal.endswith("'")
    assert literal.startswith("'")


def test_build_profile_query_rejects_unsafe_identifier() -> None:
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        build_profile_query("source; DROP TABLE source")


def test_build_merged_targets_query_rejects_unsafe_identifier() -> None:
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        build_merged_targets_query(["unnest_0", "evil) SELECT 1 --"])


def test_build_merged_targets_query_requires_a_relation() -> None:
    with pytest.raises(ValueError, match="at least one relation"):
        build_merged_targets_query([])


def test_unnest_query_embeds_the_path_as_a_literal() -> None:
    query = build_part_unnest_query("data/part-00000.parquet")
    assert "read_parquet('data/part-00000.parquet')" in query
    for column in TARGET_COLUMNS:
        assert column in query


def test_unnest_query_applies_the_documented_derivation_rules() -> None:
    query = build_part_unnest_query("p.parquet")
    # accession normalization, amendment predicate, bundle fallback, hashing
    assert "replace(accession_number, '-', '')" in query
    assert "upper(form_clean) LIKE '%/A'" in query
    assert "upper(form_clean) LIKE '%_A'" in query
    assert "accession_number || '.txt'" in query
    assert "ltrim(source_cik, '0')" in query
    assert query.count("sha256(") >= 3
    # occurrences are unique even when a registrant is re-fetched
    assert "occurrence_rank" in query
    assert "ORDER BY source_cik, accession, document_path" in query


def test_unnest_query_normalizes_whitespace_primary_documents() -> None:
    """v1 compared against '' only; the engine strips. v2 aligns with the engine."""
    query = build_part_unnest_query("p.parquet")
    assert "nullif(trim(primary_document), '')" in query


def test_profile_query_dedups_on_latest_fetched_at() -> None:
    query = build_profile_query("source")
    assert "PARTITION BY cik" in query
    assert "ORDER BY fetched_at DESC NULLS LAST" in query
    assert "WHERE rn = 1" in query
    assert "ORDER BY cik" in query
