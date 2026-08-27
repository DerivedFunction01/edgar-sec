import pytest

from defs.viewer.sql_guard import SqlGuardError, validate_read_only


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1",
        "select * from t",
        "  WITH cte AS (SELECT 1 AS x) SELECT x FROM cte  ",
        "DESCRIBE SELECT * FROM t",
        "EXPLAIN SELECT 1",
        "SHOW TABLES",
        "PRAGMA table_info('t')",
        "SELECT ';' AS semicolon_inside_string",
        "SELECT 1 -- trailing comment; careful\n",
        "SELECT 'a''b; still a string' AS value",
        "/* leading; comment */ SELECT 1",
        "SELECT 1;",
    ],
)
def test_read_only_queries_are_accepted(query):
    assert validate_read_only(query).strip() != ""


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        ";",
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE t",
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET x = 1",
        "DELETE FROM t",
        "CREATE TABLE t (x INT)",
        "DROP TABLE t",
        "ATTACH '/tmp/x.db' AS evil",
        "SET memory_limit = '1GB'",
        "INSTALL httpfs",
        "LOAD httpfs",
        "COPY (SELECT 1) TO '/tmp/out.parquet'",
        "SELECT 1 -- comment\n; SELECT 2",
    ],
)
def test_non_read_or_multi_statements_are_rejected(query):
    with pytest.raises(SqlGuardError):
        validate_read_only(query)
