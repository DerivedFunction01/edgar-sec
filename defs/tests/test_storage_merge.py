from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq

from defs.storage import (
    MergeValidationSpec,
    concat_to_parquet,
    connect,
    count_nested_values,
    count_rows,
    duplicate_values,
    jsonl_columns,
    ordered_keys,
    validate_files,
)

SCHEMA = pa.schema(
    [
        ("cik", pa.string()),
        ("schema_version", pa.string()),
        ("input_fingerprint", pa.string()),
        ("status", pa.string()),
        (
            "filings",
            pa.list_(
                pa.struct(
                    [
                        ("accession_number_normalized", pa.string()),
                        ("form", pa.string()),
                    ]
                )
            ),
        ),
    ]
)

SPEC = MergeValidationSpec(
    schema=SCHEMA,
    key_field="cik",
    schema_version="1.0.0",
    fingerprint="fp",
    terminal_statuses=("failed", "ok", "partial"),
    uniqueness_paths=(("filings", "accession_number_normalized"),),
    order_by=("cik",),
)


def make_rows(rows):
    return rows


def write_parquet(tmp_path, name, rows):
    path = tmp_path / name
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), str(path))
    return str(path)


def write_jsonl(tmp_path, name, rows):
    path = tmp_path / name
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(row) + "\n" for row in rows)
    return str(path)


def base_row(cik, accessions=("a-1",)):
    return {
        "cik": cik,
        "schema_version": "1.0.0",
        "input_fingerprint": "fp",
        "status": "ok",
        "filings": [
            {"accession_number_normalized": acc, "form": "10-K"} for acc in accessions
        ],
    }


def test_validate_files_counts_and_coverage(tmp_path):
    p1 = write_parquet(
        tmp_path, "a.parquet", [base_row("1", ("a-1",)), base_row("2", ("a-2",))]
    )
    con = connect(threads=2, memory_limit="1GB")
    validation = validate_files(con, "parquet", [p1], SPEC)
    assert validation.row_count == 2
    assert validation.distinct_keys == 2
    assert validation.invalid_field_rows == 0
    assert validation.duplicate_keys == ()
    assert (
        validation.uniqueness_duplicate_counts[
            ("filings", "accession_number_normalized")
        ]
        == 0
    )


def test_validate_files_flags_invalid_fields(tmp_path):
    rows = [base_row("1"), {**base_row("2"), "input_fingerprint": "other"}]
    p1 = write_parquet(tmp_path, "a.parquet", rows)
    con = connect(threads=2, memory_limit="1GB")
    validation = validate_files(con, "parquet", [p1], SPEC)
    assert validation.invalid_field_rows == 1


def test_validate_files_flags_duplicate_keys_and_uniqueness(tmp_path):
    rows = [
        base_row("1", ("acc-1",)),
        base_row("1", ("acc-2",)),
        base_row("2", ("acc-3",)),
        base_row("3", ("acc-3",)),
    ]
    p1 = write_parquet(tmp_path, "a.parquet", rows)
    con = connect(threads=2, memory_limit="1GB")
    validation = validate_files(con, "parquet", [p1], SPEC)
    assert validation.duplicate_keys == ("1",)
    assert (
        validation.uniqueness_duplicate_counts[
            ("filings", "accession_number_normalized")
        ]
        == 1
    )
    assert duplicate_values(
        con, "parquet", [p1], SCHEMA, ("filings", "accession_number_normalized")
    ) == ["acc-3"]


def test_validate_files_supports_jsonl(tmp_path):
    rows = [base_row("1"), base_row("2")]
    p1 = write_jsonl(tmp_path, "a.jsonl", rows)
    con = connect(threads=2, memory_limit="1GB")
    validation = validate_files(con, "jsonl", [p1], SPEC)
    assert validation.row_count == 2
    assert validation.distinct_keys == 2
    assert validation.invalid_field_rows == 0


def test_ordered_keys_returns_spec_order(tmp_path):
    rows = [base_row("9"), base_row("1"), base_row("5")]
    p1 = write_parquet(tmp_path, "a.parquet", rows)
    con = connect(threads=2, memory_limit="1GB")
    assert ordered_keys(con, "parquet", p1, SPEC) == ["1", "5", "9"]


def test_concat_to_parquet_writes_deterministic_order(tmp_path):
    p1 = write_parquet(tmp_path, "a.parquet", [base_row("2", ("x-1",))])
    p2 = write_parquet(tmp_path, "b.parquet", [base_row("1", ("y-1",))])
    con = connect(threads=2, memory_limit="1GB")
    output = tmp_path / "final.parquet"
    concat_to_parquet(con, "parquet", [p1, p2], SPEC, str(output))
    assert count_rows(con, str(output)) == 2
    assert ordered_keys(con, "parquet", str(output), SPEC) == ["1", "2"]
    assert (
        count_nested_values(
            con,
            "parquet",
            [str(output)],
            SCHEMA,
            ("filings", "accession_number_normalized"),
        )
        == 2
    )


def test_concat_to_parquet_reads_jsonl(tmp_path):
    p1 = write_jsonl(tmp_path, "a.jsonl", [base_row("1", ("j-1",))])
    con = connect(threads=2, memory_limit="1GB")
    output = tmp_path / "final.parquet"
    concat_to_parquet(con, "jsonl", [p1], SPEC, str(output))
    table = pq.read_table(str(output), schema=SCHEMA)
    assert table.column("cik").to_pylist() == ["1"]


def test_jsonl_columns_spec_is_generated_from_schema():
    columns = jsonl_columns(SCHEMA)
    assert columns["cik"] == "VARCHAR"
    assert columns["filings"].startswith("STRUCT(")
    assert columns["filings"].endswith("[]")
