"""Unit tests for apps.viewer.console."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.apps.viewer.console import (
    MAX_PAYLOAD_BYTES,
    MAX_SQL_ROWS,
    run_dataset_sql,
)
from edgar_sec.apps.viewer.datasets import DatasetError, DatasetRef

_CIK = pa.schema(
    [
        pa.field("cik", pa.int64()),
        pa.field("name", pa.string()),
        pa.field("form", pa.string()),
    ]
)


@pytest.fixture
def ref(tmp_path: Path) -> DatasetRef:
    path = tmp_path / "one.parquet"
    pq.write_table(
        pa.table(
            {
                "cik": pa.array([1, 2, 3], pa.int64()),
                "name": pa.array(["alpha", "beta", "gamma"], pa.string()),
                "form": pa.array(["10-K", "10-Q", "10-K"], pa.string()),
            },
            schema=_CIK,
        ),
        path,
    )
    return DatasetRef(dataset_id="one", paths=(path,))


def test_a_select_runs_against_the_selected_dataset(ref: DatasetRef) -> None:
    result = run_dataset_sql(ref, "SELECT cik FROM dataset ORDER BY cik")
    assert result["columns"] == ["cik"]
    assert [row["cik"] for row in result["rows"]] == [1, 2, 3]
    assert result["truncated"] is False
    assert result["elapsed_ms"] >= 0


def test_an_aggregate_is_allowed(ref: DatasetRef) -> None:
    result = run_dataset_sql(ref, "SELECT form, COUNT(*) AS n FROM dataset GROUP BY 1")
    assert {row["form"]: row["n"] for row in result["rows"]} == {"10-K": 2, "10-Q": 1}


def test_a_cte_is_allowed(ref: DatasetRef) -> None:
    result = run_dataset_sql(ref, "WITH x AS (SELECT 1 AS n) SELECT * FROM x")
    assert result["rows"] == [{"n": 1}]


def test_a_trailing_semicolon_is_tolerated(ref: DatasetRef) -> None:
    assert run_dataset_sql(ref, "SELECT 1 AS n;")["rows"] == [{"n": 1}]


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE dataset",
        "INSERT INTO dataset VALUES (1)",
        "CREATE TABLE t (a int)",
        "ATTACH '/tmp/x.db'",
        "DELETE FROM dataset",
        "SELECT 1; DROP TABLE dataset",
    ],
)
def test_writes_and_stacked_statements_are_refused(ref: DatasetRef, query: str) -> None:
    with pytest.raises(DatasetError):
        run_dataset_sql(ref, query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM read_parquet('/etc/passwd')",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_json_auto('/etc/passwd')",
        "SELECT * FROM sqlite_scan('/tmp/x.db', 't')",
        "SELECT * FROM READ_PARQUET('/etc/passwd')",
    ],
)
def test_table_functions_are_refused(ref: DatasetRef, query: str) -> None:
    """A console scoped to one dataset must not be able to name another file."""
    with pytest.raises(DatasetError, match="table function"):
        run_dataset_sql(ref, query)


def test_the_console_cannot_see_anything_but_the_dataset(ref: DatasetRef) -> None:
    """The selected part list is the whole reachable world.

    DuckDB's own ``information_schema`` is a built-in and is always queryable;
    what must not be visible is a *second* relation. A console that could name
    another relation would make the row cap and the table-function ban
    pointless, because the data would simply be reachable under another name.
    """
    result = run_dataset_sql(ref, "SELECT table_name FROM information_schema.tables")
    assert [row["table_name"] for row in result["rows"]] == ["dataset"]


def test_a_relation_that_does_not_exist_is_not_reachable(ref: DatasetRef) -> None:
    with pytest.raises(DatasetError):
        run_dataset_sql(ref, "SELECT * FROM other_dataset")


def test_the_row_cap_is_applied_by_the_wrapper(ref: DatasetRef) -> None:
    """The cap holds even when the user's own query is unbounded."""
    result = run_dataset_sql(
        ref, "SELECT * FROM dataset UNION ALL SELECT * FROM dataset"
    )
    assert len(result["rows"]) <= MAX_SQL_ROWS


def test_truncation_is_reported(ref: DatasetRef) -> None:
    result = run_dataset_sql(ref, "SELECT * FROM dataset")
    assert result["truncated"] is False


def test_a_syntax_error_surfaces_as_a_dataset_error(ref: DatasetRef) -> None:
    with pytest.raises(DatasetError):
        run_dataset_sql(ref, "SELECT FROM WHERE")


def test_an_interrupted_query_says_so(ref: DatasetRef) -> None:
    with pytest.raises(DatasetError, match="interrupted"):
        run_dataset_sql(ref, "SELECT count(*) FROM range(100000000000)", timeout_s=0.4)


def test_a_result_is_json_safe(ref: DatasetRef) -> None:
    """No Decimal, NaN, or bytes may reach the encoder."""
    result = run_dataset_sql(
        ref, "SELECT CAST(1.5 AS DECIMAL(10,2)) AS d, 0.0/0.0 AS bad"
    )
    assert result["rows"] == [{"d": "1.50", "bad": None}]


def test_max_payload_bytes_is_positive() -> None:
    assert MAX_PAYLOAD_BYTES > 0
