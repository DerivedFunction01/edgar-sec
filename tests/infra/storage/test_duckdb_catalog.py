"""Unit tests for the catalog SQL builders."""

from __future__ import annotations

import duckdb
import pytest

from edgar_sec.domain.filing_catalog.filters import normalize_suffixes
from edgar_sec.domain.filing_catalog.schemas import TARGET_COLUMNS
from edgar_sec.infra.storage.duckdb_catalog import (
    amendment_sql,
    build_part_unnest_query,
    build_profile_query,
    copy_query_to_parquet,
    sql_literal,
    suffix_sql,
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


def test_unnest_query_embeds_the_path_as_a_literal() -> None:
    query = build_part_unnest_query("data/part-00000.parquet")
    assert "read_parquet('data/part-00000.parquet')" in query
    for column in TARGET_COLUMNS:
        assert column in query


def test_unnest_query_takes_exactly_one_source_part() -> None:
    """A shard is written per source part, so the builder reads exactly one file.

    Concatenating the whole part list into one ``read_parquet([...])`` is what made
    the unnest unbounded: the correlated lateral below then planned as a delim join
    over every part at once. One file per query keeps peak memory proportional to a
    part rather than to the cohort.
    """
    query = build_part_unnest_query("data/part-00007.parquet")
    assert "read_parquet('data/part-00007.parquet')" in query
    assert "read_parquet([" not in query


def test_unnest_query_does_not_correlate_the_unnest() -> None:
    """The unnest must stay uncorrelated.

    ``LATERAL (SELECT UNNEST(t.filings))`` makes DuckDB insert a ``DELIM_SCAN``,
    which pins the entire nested value of every source row before emitting
    anything. That pin does not spill, so it exhausts the memory limit where the
    uncorrelated form streams. This asserts the *shape*; the plan-level assertion
    below asserts the consequence.
    """
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


def test_unnest_query_executes_without_a_delim_join(tmp_path, sample_source) -> None:
    """The query must run, and its plan must contain no delim join.

    This is the assertion that would have caught the original defect. The shape
    checks above fail loudly if someone reintroduces the correlated lateral, but
    only a real plan proves DuckDB stopped inserting the delim scan on its own.
    ``EXPLAIN`` is used rather than ``EXPLAIN ANALYZE`` so the test stays a fast
    static check with no data movement.
    """
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


def test_suffix_sql_is_true_when_unconstrained() -> None:
    """An empty suffix set yields a predicate the caller can apply unconditionally."""
    assert suffix_sql("document_path", ()) == "TRUE"


def test_suffix_sql_matches_each_allowed_suffix() -> None:
    predicate = suffix_sql("document_path", ("htm", "txt"))
    assert predicate == (
        "(lower(document_path) LIKE '%.htm' OR lower(document_path) LIKE '%.txt')"
    )


def test_suffix_sql_binds_suffixes_as_literals() -> None:
    """A suffix is user input; the allowlist rejects anything quote-shaped."""
    with pytest.raises(ValueError, match="invalid document suffix"):
        normalize_suffixes(("x'; DROP TABLE t; --",))
    with pytest.raises(ValueError, match="invalid document suffix"):
        normalize_suffixes(("--",))


def test_suffix_sql_rejects_an_unsafe_column() -> None:
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        suffix_sql("document_path) OR 1=1 --", ("htm",))


def test_amendment_sql_covers_every_policy() -> None:
    assert amendment_sql("both") == "TRUE"
    assert amendment_sql("original") == "is_amendment = false"
    assert amendment_sql("amendments") == "is_amendment = true"


def test_amendment_sql_rejects_an_unknown_policy() -> None:
    with pytest.raises(ValueError, match="amendment must be one of"):
        amendment_sql("amendmented")
