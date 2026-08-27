import pytest

from defs.viewer.datasets import (
    DatasetError,
    DatasetRef,
    dataset_column_stats,
    dataset_rows,
    dataset_schema,
    run_dataset_sql,
)
import pyarrow as pa
import pyarrow.parquet as parquet

from viewer_fixtures import (  # noqa: F401 - fixtures registered via import
    artifacts_root,
    chunk_dataset,
    parquet_dataset,
    write_parquet,
)


def _ref(dataset) -> DatasetRef:
    fmt = "parquet" if str(dataset["path"]).endswith(".parquet") else "jsonl"
    return DatasetRef(dataset_id=dataset["id"], path=dataset["path"], fmt=fmt)


def test_schema_reports_names_types_and_nulls(chunk_dataset):
    ref = _ref(chunk_dataset)
    columns = dataset_schema(ref)
    by_name = {column["name"]: column for column in columns}

    assert set(by_name) == {"cik", "name", "status", "filings"}
    assert by_name["cik"]["null_count"] == 0
    assert by_name["status"]["null_count"] == 0
    assert by_name["status"]["approx_distinct"] == 2
    assert (
        "STRUCT" in by_name["filings"]["duckdb_type"].upper()
        or "MAP" in by_name["filings"]["duckdb_type"].upper()
        or "JSON" in by_name["filings"]["duckdb_type"].upper()
    )


def test_rows_pages_sorts_and_searches(chunk_dataset):
    ref = _ref(chunk_dataset)

    page = dataset_rows(ref, offset=0, limit=2, sort="cik", direction="asc")
    assert [row["cik"] for row in page["items"]] == [
        "0000000020",
        "0000001761",
    ]
    assert page["has_more"] is True
    assert page["next_cursor"] == 2

    second = dataset_rows(ref, offset=2, limit=2, sort="cik", direction="asc")
    assert [row["cik"] for row in second["items"]] == ["0000037996"]
    assert second["has_more"] is False
    assert second["next_cursor"] is None

    searched = dataset_rows(ref, offset=0, limit=10, search="ford")
    assert [row["cik"] for row in searched["items"]] == ["0000037996"]

    single_column = dataset_rows(
        ref, offset=0, limit=10, search="K TRON", search_columns=["name"]
    )
    assert [row["cik"] for row in single_column["items"]] == ["0000000020"]


def test_rows_preserves_nested_values(parquet_dataset):
    ref = _ref(parquet_dataset)
    page = dataset_rows(ref, offset=0, limit=10)
    first = page["items"][0]
    assert first["filings"][0]["form"] == "10-K"
    assert first["filings"][0]["file_count"] == 3


def test_typed_filters_are_and_composed(parquet_dataset):
    ref = _ref(parquet_dataset)
    assert [
        row["cik"]
        for row in dataset_rows(
            ref,
            limit=10,
            filters=[
                {"column": "status", "op": "eq", "value": "ok"},
                {"column": "cik", "op": "eq", "value": "0000001761"},
            ],
        )["items"]
    ] == ["0000001761"]
    assert (
        dataset_rows(
            ref,
            limit=10,
            filters=[{"column": "status", "op": "contains", "value": "missing"}],
        )["items"]
        == []
    )
    with pytest.raises(ValueError):
        dataset_rows(
            ref, limit=10, filters=[{"column": "status", "op": "gt", "value": "x"}]
        )


def test_text_ops_work_on_nested_and_empty_semantics(parquet_dataset):
    ref = _ref(parquet_dataset)
    matches = dataset_rows(
        ref, limit=10, filters=[{"column": "filings", "op": "contains", "value": "10-K"}]
    )
    assert len(matches["items"]) == 2
    kept = dataset_rows(ref, limit=10, filters=[{"column": "filings", "op": "not_empty"}])
    assert len(kept["items"]) == 2
    with pytest.raises(ValueError):
        dataset_rows(
            ref, limit=10, filters=[{"column": "filings", "op": "gt", "value": "1"}]
        )


def test_order_ops_on_numeric_and_bool_rejected(artifacts_root):
    path = artifacts_root / "metadata" / "canonical" / "typed.parquet"
    write_parquet(
        path,
        pa.table(
            {
                "n": pa.array([1, None, 3], type=pa.int64()),
                "flag": pa.array([True, False, None], type=pa.bool_()),
            }
        ),
    )
    ref = DatasetRef(dataset_id="typed", path=path, fmt="parquet")
    empty = dataset_rows(ref, limit=10, filters=[{"column": "n", "op": "empty"}])
    assert len(empty["items"]) == 1
    kept = dataset_rows(
        ref, limit=10, filters=[{"column": "n", "op": "gt", "value": 1}]
    )
    assert [row["n"] for row in kept["items"]] == [3]
    assert dataset_rows(
        ref, limit=10, filters=[{"column": "flag", "op": "eq", "value": "true"}]
    )["items"][0]["flag"] is True
    with pytest.raises(ValueError):
        dataset_rows(ref, limit=10, filters=[{"column": "flag", "op": "lt", "value": True}])


def test_union_ref_reads_all_paths(artifacts_root):
    first = artifacts_root / "metadata" / "runs" / "run-1" / "a.parquet"
    second = artifacts_root / "metadata" / "runs" / "run-1" / "b.parquet"
    first.parent.mkdir(parents=True)
    parquet.write_table(pa.table({"id": [1], "name": ["one"]}), str(first))
    parquet.write_table(pa.table({"id": [2], "name": ["two"]}), str(second))
    ref = DatasetRef(
        dataset_id="union", path=first, fmt="parquet", paths=(first, second)
    )
    assert {row["id"] for row in dataset_rows(ref, limit=10)["items"]} == {1, 2}


def test_parquet_rows_include_total_without_scan_style_count(parquet_dataset):
    ref = _ref(parquet_dataset)
    page = dataset_rows(ref, offset=0, limit=1)
    assert page["total_rows"] == 2


def test_jsonl_rows_have_no_total_by_default(chunk_dataset):
    ref = _ref(chunk_dataset)
    page = dataset_rows(ref, offset=0, limit=10)
    assert page["total_rows"] is None


def test_validation_errors(chunk_dataset):
    ref = _ref(chunk_dataset)
    with pytest.raises(ValueError):
        dataset_rows(ref, offset=0, limit=5000)
    with pytest.raises(ValueError):
        dataset_rows(ref, offset=0, limit=10, sort="not_a_column")
    with pytest.raises(ValueError):
        dataset_rows(ref, offset=0, limit=10, search="x", search_columns=["nope"])
    with pytest.raises(ValueError):
        dataset_rows(ref, offset=0, limit=10, sort="cik", direction="sideways")


def test_column_stats_include_top_values(chunk_dataset):
    ref = _ref(chunk_dataset)
    columns = dataset_column_stats(ref)
    status = next(column for column in columns if column["name"] == "status")
    top = {item["value"]: item["count"] for item in status["top_values"]}
    assert top == {"ok": 2, "failed": 1}


def test_sql_guard_rejects_writes_and_allows_reads(chunk_dataset):
    ref = _ref(chunk_dataset)

    result = run_dataset_sql(ref, "SELECT cik, status FROM dataset WHERE status = 'ok'")
    assert result["columns"] == ["cik", "status"]
    assert len(result["rows"]) == 2

    with pytest.raises(DatasetError):
        run_dataset_sql(ref, "INSERT INTO x VALUES (1)")
    with pytest.raises(DatasetError):
        run_dataset_sql(ref, "DELETE FROM dataset")
    with pytest.raises(DatasetError):
        run_dataset_sql(ref, "ATTACH '/tmp/x.db' AS evil")
    with pytest.raises(DatasetError):
        run_dataset_sql(ref, "SELECT 1; DROP TABLE dataset")
    with pytest.raises(DatasetError):
        run_dataset_sql(ref, "SELECT * FROM read_parquet('/etc/passwd')")
    with pytest.raises(DatasetError):
        run_dataset_sql(ref, "   ")
