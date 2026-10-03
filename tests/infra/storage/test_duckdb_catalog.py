"""Unit tests for the catalog SQL builders."""

from __future__ import annotations

import duckdb
import pytest

from edgar_sec.domain.filing_catalog.filters import (
    RecurringDateClause,
    normalize_suffixes,
    parse_date_selection,
)
from edgar_sec.domain.filing_catalog.schemas import TARGET_COLUMNS
from edgar_sec.infra.storage.duckdb_catalog import (
    PARSED_DATE_ALIAS,
    build_part_unnest_query,
    build_profile_query,
    copy_query_to_parquet,
    date_projection_sql,
    date_selection_sql,
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
    # accession normalization, bundle fallback, hashing
    assert "replace(accession_number, '-', '')" in query
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


def test_date_selection_sql_is_true_when_unconstrained() -> None:
    """The empty selection applies no predicate, matching the other builders.

    It is not the same answer as a nonempty selection: an empty one keeps rows
    whose ``report_date`` is missing, because there is nothing to place them
    against.
    """
    assert date_selection_sql(()) == "TRUE"


def test_date_projection_sql_parses_the_text_column_under_a_fixed_alias() -> None:
    """``report_date`` is text; the predicate needs a DATE to compare."""
    assert date_projection_sql("report_date") == (
        f"TRY_CAST(report_date AS DATE) AS {PARSED_DATE_ALIAS}"
    )


def test_date_projection_sql_rejects_an_unsafe_column() -> None:
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        date_projection_sql("report_date) OR 1=1 --")


def test_date_selection_sql_bounds_absolute_clauses_inclusively() -> None:
    predicate = date_selection_sql(parse_date_selection("2005Q3..2008Q1"))
    assert predicate == (
        f"{PARSED_DATE_ALIAS} BETWEEN DATE '2005-07-01' AND DATE '2008-03-31'"
    )


def test_date_selection_sql_keeps_one_side_of_an_open_bound() -> None:
    open_start = date_selection_sql(parse_date_selection("2008.."))
    open_end = date_selection_sql(parse_date_selection("..2007"))
    assert open_start == f"{PARSED_DATE_ALIAS} >= DATE '2008-01-01'"
    assert open_end == f"{PARSED_DATE_ALIAS} <= DATE '2007-12-31'"


def test_date_selection_sql_ands_the_period_with_its_year_bounds() -> None:
    """The quarter filter and the year bounds are separate conditions.

    Keeping them visible in the emitted SQL is what makes the distinction between
    ``@Q1[2011..2015]`` and ``@Q1`` checkable by reading the predicate.
    """
    predicate = date_selection_sql(parse_date_selection("@Q1[2011..2015]"))
    assert predicate == (
        "("
        f"date_part('quarter', {PARSED_DATE_ALIAS}) IN (1)"
        f" AND date_part('year', {PARSED_DATE_ALIAS}) >= 2011"
        f" AND date_part('year', {PARSED_DATE_ALIAS}) <= 2015"
        ")"
    )


def test_date_selection_sql_selects_calendar_months() -> None:
    predicate = date_selection_sql(parse_date_selection("@M12"))
    assert predicate == f"(date_part('month', {PARSED_DATE_ALIAS}) IN (12))"


def test_date_selection_sql_ors_the_clauses_and_parenthesizes_them() -> None:
    """A caller conjoins this with AND, so the disjunction must carry its own
    parentheses or ``a AND b OR c`` silently changes its meaning."""
    predicate = date_selection_sql(parse_date_selection("2024,@Q1"))
    assert predicate == (
        "("
        f"{PARSED_DATE_ALIAS} BETWEEN DATE '2024-01-01' AND DATE '2024-12-31'"
        f" OR (date_part('quarter', {PARSED_DATE_ALIAS}) IN (1))"
        ")"
    )


def test_date_selection_sql_binds_dates_as_literals_not_interpolation() -> None:
    predicate = date_selection_sql(parse_date_selection("2024-01-05"))
    assert "DATE '2024-01-05'" in predicate
    bounded = date_selection_sql([RecurringDateClause("quarter", (1,), 1999, 2001)])
    assert bounded.count("1999") == 1


def _select_report_dates(selection_text: str, rows: list[str]) -> list[str]:
    """Run the predicate over ``rows`` the way a caller must wire it.

    Both wirings are executed so the tests pin that they select the same rows;
    the projection exists for speed, not for a different answer.
    """
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE src(report_date VARCHAR)")
        con.executemany("INSERT INTO src VALUES (?)", [(value,) for value in rows])
        selection = parse_date_selection(selection_text)
        predicate = date_selection_sql(selection)
        projection = date_projection_sql("report_date")
        selected = con.execute(
            f"SELECT report_date FROM (SELECT *, {projection} FROM src) "
            f"WHERE {predicate}"
        ).fetchall()
        inline = con.execute(
            "SELECT report_date FROM src WHERE "
            + predicate.replace(PARSED_DATE_ALIAS, "TRY_CAST(report_date AS DATE)")
        ).fetchall()
        assert selected == inline, "projected and inline spellings must agree"
        return [row[0] for row in selected]
    finally:
        con.close()


def test_date_selection_sql_matches_calendar_bounds_on_real_shaped_values() -> None:
    rows = [
        "1998-12-31",
        "1999-03-31",
        "2005-06-30",
        "2005-07-01",
        "2008-03-31",
        "2008-04-01",
        "2024-06-30",
        "2024-07-01",
    ]
    assert _select_report_dates("2005Q3..2008Q1", rows) == [
        "2005-07-01",
        "2008-03-31",
    ]
    # 2008-03-31 is Q1, so an unbounded ``@Q1`` keeps it while a bounded one
    # drops it -- the distinction the two spellings exist to express.
    assert _select_report_dates("@Q1", rows) == ["1999-03-31", "2008-03-31"]
    assert _select_report_dates("@Q1[1999..2005]", rows) == ["1999-03-31"]
    assert _select_report_dates("@Q1[1999..2001]", rows) == ["1999-03-31"]
    assert _select_report_dates("@M06,@M07", rows) == [
        "2005-06-30",
        "2005-07-01",
        "2024-06-30",
        "2024-07-01",
    ]
    assert _select_report_dates("..2007", rows) == [
        "1998-12-31",
        "1999-03-31",
        "2005-06-30",
        "2005-07-01",
    ]


def test_date_selection_sql_ors_clauses_without_duplicating_a_row() -> None:
    """Two windows that both cover a date must still yield that date once."""
    rows = ["2024-03-15", "2024-08-15"]
    assert _select_report_dates("2024Q1,2024Q2", rows) == ["2024-03-15"]


def test_empty_selection_keeps_rows_with_no_readable_report_date() -> None:
    """The catalog stores a missing report_date as an empty string."""
    rows = ["", "2024-03-15"]
    assert _select_report_dates("", rows) == rows


def test_nonempty_selection_excludes_rows_with_no_readable_report_date() -> None:
    """A missing date has no interval and no quarter, so it cannot be placed."""
    rows = [
        "",
        "   ",
        "not-a-date",
        "2024-13-45",
        "2024-03-15",
        "2024-08-15",
    ]
    assert _select_report_dates("2024", rows) == ["2024-03-15", "2024-08-15"]
    assert _select_report_dates("@Q3", rows) == ["2024-08-15"]
