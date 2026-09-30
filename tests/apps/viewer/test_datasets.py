"""Unit tests for apps.viewer.datasets."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import zstandard

from edgar_sec.apps.viewer.datasets import (
    MAX_BLOB_PREVIEW,
    MAX_LIMIT,
    DatasetError,
    DatasetRef,
    dataset_blob,
    dataset_column_stats,
    dataset_rows,
    dataset_schema,
)

_CIK = pa.schema([pa.field("cik", pa.int64()), pa.field("name", pa.string())])
_CIKS = pa.schema(
    [
        pa.field("cik", pa.int64()),
        pa.field("flag", pa.bool_()),
        pa.field("blank", pa.string()),
    ]
)

# Long enough that zstd actually shrinks it: a tiny payload is *larger* after
# compression because the frame header costs more than the body saves.
_BLOB_BODY = ("<html>" + "filing body " * 200 + "</html>").encode()


def _write(path: Path, table: pa.Table) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return path


@pytest.fixture
def one_part(tmp_path: Path) -> DatasetRef:
    path = _write(
        tmp_path / "one.parquet",
        pa.table(
            {
                "cik": pa.array([1, 2, 3], pa.int64()),
                "name": pa.array(["alpha", "beta", "gamma"], pa.string()),
            },
            schema=_CIK,
        ),
    )
    return DatasetRef(dataset_id="one", paths=(path,))


@pytest.fixture
def three_parts(tmp_path: Path) -> DatasetRef:
    paths = tuple(
        _write(
            tmp_path / f"part-{index}.parquet",
            pa.table(
                {
                    "cik": pa.array([index * 10], pa.int64()),
                    "name": pa.array([f"CO {index}"], pa.string()),
                },
                schema=_CIK,
            ),
        )
        for index in range(3)
    )
    return DatasetRef(dataset_id="three", paths=paths)


@pytest.fixture
def typed(tmp_path: Path) -> DatasetRef:
    path = _write(
        tmp_path / "typed.parquet",
        pa.table(
            {
                "cik": pa.array([1, 2, 3], pa.int64()),
                "flag": pa.array([True, False, None], pa.bool_()),
                "blank": pa.array(["x", "", None], pa.string()),
            },
            schema=_CIKS,
        ),
    )
    return DatasetRef(dataset_id="typed", paths=(path,))


@pytest.fixture
def blobbed(tmp_path: Path) -> DatasetRef:
    compressed = zstandard.ZstdCompressor().compress(_BLOB_BODY)
    path = _write(
        tmp_path / "payload.parquet",
        pa.table(
            {
                "doc_id": pa.array(["d1", "d2"], pa.string()),
                "raw_payload": pa.array([compressed, b"tiny"], pa.binary()),
            },
            schema=pa.schema(
                [pa.field("doc_id", pa.string()), pa.field("raw_payload", pa.binary())]
            ),
        ),
    )
    return DatasetRef(dataset_id="blobbed", paths=(path,))


# --- schema ----------------------------------------------------------------


def test_schema_reports_names_types_and_nulls(one_part: DatasetRef) -> None:
    columns = dataset_schema(one_part)
    assert [column["name"] for column in columns] == ["cik", "name"]
    assert columns[0]["duckdb_type"] == "BIGINT"
    assert all(column["null_count"] == 0 for column in columns)
    assert columns[0]["approx_distinct"] == 3


def test_schema_counts_nulls(typed: DatasetRef) -> None:
    by_name = {column["name"]: column for column in dataset_schema(typed)}
    assert by_name["flag"]["null_count"] == 1
    assert by_name["blank"]["null_count"] == 1


def test_schema_spans_every_part(three_parts: DatasetRef) -> None:
    columns = {column["name"]: column for column in dataset_schema(three_parts)}
    assert columns["cik"]["approx_distinct"] == 3


def test_schema_reports_a_missing_part_rather_than_an_empty_schema(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "a.parquet", pa.table({"cik": pa.array([1], pa.int64())}))
    ref = DatasetRef(dataset_id="gone", paths=(path,))
    path.unlink()
    # The ref validated the part when it was built; a part removed afterwards
    # must surface as a read error rather than as an empty schema.
    with pytest.raises(DatasetError, match="a.parquet"):
        dataset_schema(ref)


def test_a_part_absent_at_construction_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="absent"):
        DatasetRef(dataset_id="never", paths=(tmp_path / "missing.parquet",))


# --- rows ------------------------------------------------------------------


def test_rows_page_with_limit_plus_one(one_part: DatasetRef) -> None:
    page = dataset_rows(one_part, limit=2, sort="cik")
    assert [row["cik"] for row in page["items"]] == [1, 2]
    assert page["has_more"] is True
    assert page["next_cursor"] == 2


def test_last_page_reports_no_more(one_part: DatasetRef) -> None:
    page = dataset_rows(one_part, limit=10, sort="cik")
    assert page["has_more"] is False
    assert page["next_cursor"] is None
    assert page["total_rows"] == 3


def test_rows_offset_pages_forward(one_part: DatasetRef) -> None:
    page = dataset_rows(one_part, offset=2, limit=2, sort="cik")
    assert [row["cik"] for row in page["items"]] == [3]


def test_rows_sort_direction(typed: DatasetRef) -> None:
    page = dataset_rows(typed, sort="cik", direction="desc", limit=1)
    assert page["items"][0]["cik"] == 3


def test_rows_search_spans_columns(one_part: DatasetRef) -> None:
    page = dataset_rows(one_part, search="bet")
    assert [row["cik"] for row in page["items"]] == [2]


def test_rows_reject_an_unknown_sort_column(one_part: DatasetRef) -> None:
    with pytest.raises(DatasetError, match="unknown sort column"):
        dataset_rows(one_part, sort="nope")


@pytest.mark.parametrize("bad", [0, MAX_LIMIT + 1, -1])
def test_rows_reject_an_out_of_range_limit(one_part: DatasetRef, bad: int) -> None:
    with pytest.raises(DatasetError, match="limit"):
        dataset_rows(one_part, limit=bad)


def test_rows_reject_a_bad_direction(one_part: DatasetRef) -> None:
    with pytest.raises(DatasetError, match="direction"):
        dataset_rows(one_part, direction="sideways")


def test_filters_are_and_composed(typed: DatasetRef) -> None:
    page = dataset_rows(
        typed,
        filters=[{"column": "cik", "op": "ge", "value": 2}],
    )
    assert [row["cik"] for row in page["items"]] == [2, 3]

    page = dataset_rows(
        typed,
        filters=[
            {"column": "cik", "op": "ge", "value": 1},
            {"column": "cik", "op": "le", "value": 2},
        ],
    )
    assert [row["cik"] for row in page["items"]] == [1, 2]


def test_text_filters_work_on_null_and_empty(typed: DatasetRef) -> None:
    empty = dataset_rows(typed, filters=[{"column": "blank", "op": "empty"}])
    assert {row["cik"] for row in empty["items"]} == {2, 3}
    not_empty = dataset_rows(typed, filters=[{"column": "blank", "op": "not_empty"}])
    assert [row["cik"] for row in not_empty["items"]] == [1]


def test_contains_filter(typed: DatasetRef) -> None:
    page = dataset_rows(
        typed, filters=[{"column": "blank", "op": "contains", "value": "x"}]
    )
    assert [row["cik"] for row in page["items"]] == [1]


def test_order_operator_is_refused_on_a_string_column(typed: DatasetRef) -> None:
    """A range on VARCHAR compares lexicographically, which is not what '>' means."""
    with pytest.raises(DatasetError, match="invalid for column"):
        dataset_rows(typed, filters=[{"column": "blank", "op": "gt", "value": "a"}])


@pytest.mark.parametrize(
    "item",
    [
        {"column": "nope", "op": "eq", "value": 1},
        {"column": "cik", "op": "sideways", "value": 1},
        {"op": "eq", "value": 1},
    ],
)
def test_filter_validation_errors(typed: DatasetRef, item: dict) -> None:
    with pytest.raises(DatasetError):
        dataset_rows(typed, filters=[item])


def test_a_filter_with_no_value_matches_nothing_rather_than_erroring(
    typed: DatasetRef,
) -> None:
    """`cik = NULL` is a legitimate (empty) filter, not a malformed request.

    A client that omits the value gets an empty page, which is a truthful answer
    to "rows where cik equals nothing". Treating it as an error would make the
    UI fail a filter the user can see and correct.
    """
    page = dataset_rows(typed, filters=[{"column": "cik", "op": "eq"}])
    assert page["items"] == []


def test_total_rows_is_suppressed_for_a_filtered_page(typed: DatasetRef) -> None:
    page = dataset_rows(typed, filters=[{"column": "cik", "op": "eq", "value": 1}])
    assert page["total_rows"] is None


def test_total_rows_is_available_for_an_unfiltered_page(one_part: DatasetRef) -> None:
    assert dataset_rows(one_part)["total_rows"] == 3


def test_rows_preserve_nulls(typed: DatasetRef) -> None:
    page = dataset_rows(typed, sort="cik")
    assert page["items"][2]["flag"] is None


# --- stats -----------------------------------------------------------------


def test_column_stats_include_top_values_for_low_cardinality(typed: DatasetRef) -> None:
    by_name = {column["name"]: column for column in dataset_column_stats(typed)}
    assert by_name["cik"]["top_values"] == []  # numeric, not VARCHAR
    values = {item["value"] for item in by_name["blank"]["top_values"]}
    assert values <= {"x", ""}


def test_column_stats_include_top_values_within_the_threshold(
    one_part: DatasetRef,
) -> None:
    by_name = {column["name"]: column for column in dataset_column_stats(one_part)}
    assert {item["value"] for item in by_name["name"]["top_values"]} == {
        "alpha",
        "beta",
        "gamma",
    }


def test_column_stats_skip_a_column_above_the_threshold(tmp_path: Path) -> None:
    """Grouping a high-cardinality column to show five values is a full sort."""
    path = _write(
        tmp_path / "wide.parquet",
        pa.table({"k": pa.array([f"v{index}" for index in range(64)], pa.string())}),
    )
    columns = dataset_column_stats(DatasetRef(dataset_id="wide", paths=(path,)))
    assert columns[0]["top_values"] == []


# --- blobs -----------------------------------------------------------------


def test_rows_mark_a_compressed_blob_instead_of_inlining_it(
    blobbed: DatasetRef,
) -> None:
    page = dataset_rows(blobbed, sort="doc_id")
    cell = page["items"][0]["raw_payload"]
    assert cell["__blob__"] is True
    assert cell["is_compressed"] is True
    assert cell["size_bytes"] > 0


def test_a_short_blob_is_inlined(blobbed: DatasetRef) -> None:
    page = dataset_rows(blobbed, sort="doc_id")
    assert page["items"][1]["raw_payload"] == "dGlueQ=="  # base64 of b"tiny"


def test_blob_is_decompressed_on_request(blobbed: DatasetRef) -> None:
    result = dataset_blob(blobbed, column="raw_payload", pk_col="doc_id", pk_val="d1")
    assert result["is_compressed"] is True
    assert result["text"] == _BLOB_BODY.decode()
    assert result["mime_type"] == "text/html"
    assert result["decompressed_bytes"] > result["compressed_bytes"]


def test_blob_preview_is_capped(blobbed: DatasetRef) -> None:
    result = dataset_blob(blobbed, column="raw_payload", row_index=0)
    assert result["preview"] == result["text"][:MAX_BLOB_PREVIEW]


def test_blob_requires_a_locator(blobbed: DatasetRef) -> None:
    with pytest.raises(DatasetError, match="pk_col"):
        dataset_blob(blobbed, column="raw_payload")


def test_blob_reports_a_missing_value(blobbed: DatasetRef) -> None:
    with pytest.raises(DatasetError, match="no blob"):
        dataset_blob(blobbed, column="raw_payload", pk_col="doc_id", pk_val="absent")


# --- the relation itself ---------------------------------------------------


def test_a_dataset_must_have_at_least_one_part() -> None:
    with pytest.raises(DatasetError, match="at least one part"):
        DatasetRef(dataset_id="empty", paths=())


def test_reader_expression_quotes_paths(three_parts: DatasetRef) -> None:
    expression = three_parts.reader_expression
    assert expression.startswith("read_parquet([")
    assert "union_by_name=true" in expression


def test_sqlite_reader_expression_requires_a_table(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    path.touch()
    with pytest.raises(DatasetError, match="must name a table"):
        _ = DatasetRef(dataset_id="db", paths=(path,), fmt="sqlite").reader_expression
    ref = DatasetRef(dataset_id="db", paths=(path,), fmt="sqlite", table="payloads")
    assert "sqlite_scan" in ref.reader_expression
