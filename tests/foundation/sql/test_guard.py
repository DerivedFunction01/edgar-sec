"""Unit tests for foundation.sql.guard."""

from __future__ import annotations

import pytest

from edgar_sec.foundation.sql.guard import (
    ALLOWED_LEADING_KEYWORDS,
    SqlGuardError,
    validate_read_only,
)

ACCEPTED = [
    "SELECT 1",
    "select cik from t",
    "  SELECT 1  ",
    "SELECT 1;",
    "SELECT ';' AS x",
    "SELECT 'it''s; fine' AS x",
    'SELECT "a;b" FROM t',
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "DESCRIBE t",
    "SHOW TABLES",
    "EXPLAIN SELECT 1",
    "PRAGMA table_info('t')",
    "-- a leading note\nSELECT 1",
    "/* block */ SELECT 1",
    "/* a */ -- b\nSELECT 1",
    "-- one\n-- two\nSELECT 1",
    "SELECT 1 -- trailing ; note",
    "SELECT 1 /* ; */",
]

REJECTED = [
    "",
    "   ",
    "DROP TABLE t",
    "INSERT INTO t VALUES (1)",
    "CREATE TABLE t (a int)",
    "ATTACH 'x.db'",
    "COPY t TO 'f.csv'",
    "PRAGMA database_list",
    "PRAGMA journal_mode=WAL",
    "SELECT 1; DROP TABLE t",
    "DROP TABLE a; SELECT 1",
]


@pytest.mark.parametrize("query", ACCEPTED)
def test_read_only_queries_are_accepted(query: str) -> None:
    assert validate_read_only(query)


@pytest.mark.parametrize("query", REJECTED)
def test_non_read_or_multi_statements_are_rejected(query: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_read_only(query)


def test_multiple_statements_are_reported_before_the_verb() -> None:
    """A stacked write reads better as 'multiple statements' than as 'bad verb'."""
    with pytest.raises(SqlGuardError, match="multiple statements"):
        validate_read_only("DROP TABLE t; SELECT 1")


def test_empty_query_is_reported_as_empty_not_as_a_verb_error() -> None:
    with pytest.raises(SqlGuardError, match="empty"):
        validate_read_only("   ;  ")


def test_pragma_is_allowed_only_in_table_info_form() -> None:
    """Bare PRAGMA can write; only the read-only form is on the allowlist."""
    assert any("PRAGMA" in keyword for keyword in ALLOWED_LEADING_KEYWORDS)
    with pytest.raises(SqlGuardError):
        validate_read_only("PRAGMA journal_mode=WAL")


def test_trailing_semicolon_is_stripped_from_the_result() -> None:
    assert validate_read_only("SELECT 1;  ") == "SELECT 1"


def test_repeated_trailing_semicolons_are_all_stripped() -> None:
    """``SELECT 1;;`` is an empty trailing statement, not a stacked one."""
    assert validate_read_only("SELECT 1;;") == "SELECT 1"


def test_unterminated_comment_is_left_for_the_engine_to_report() -> None:
    """The guard defers malformed input to DuckDB rather than guessing.

    A guard that raised here would have to invent a message; DuckDB names the
    exact syntax problem. What the guard must not do is *hang*, so the scanner
    runs the unterminated comment to end-of-string.
    """
    assert validate_read_only("SELECT 1 /* never closed")
