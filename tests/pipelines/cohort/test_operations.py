import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.pipelines.cohort.operations import (
    BinaryOp,
    CohortRef,
    compile_ast_to_sql,
    diff_cohorts,
    execute_delta_roster,
    execute_set_operation,
    parse_expression,
    sample_cohort,
    serialize_expression,
    FamilyIndexNotFoundError,
)
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.infra.storage.duckdb import connect


def _dataset(path: Path, rows: list[tuple[int, str, str]]) -> Path:
    table = pa.table(
        {
            "ordinal": [row[0] for row in rows],
            "cik_padded": [row[1] for row in rows],
            "name": [row[2] for row in rows],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return path


def _register(paths: CohortPaths, catalog: CohortCatalog, name: str, cik: str):
    roster = hashlib.sha256(name.encode()).hexdigest()
    cohort_id = f"c-{roster[:16]}"
    dataset = paths.cohort_dataset_file(cohort_id)
    dataset.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({"ordinal": [0], "cik_padded": [cik], "name": [name]}), dataset
    )
    return catalog.register_cohort(
        cohort_id=cohort_id,
        name=name,
        origin_kind="file_import",
        roster_id=roster,
        row_count=1,
        distinct_cik_count=1,
        dataset_sha256=file_sha256(dataset),
        dataset_path=paths.relative_path(dataset),
    )


def test_set_operations_prefer_left_names_and_renumber(tmp_path: Path) -> None:
    left = _dataset(
        tmp_path / "left.parquet",
        [(4, "0000000002", "Left"), (9, "0000000001", "")],
    )
    right = _dataset(
        tmp_path / "right.parquet",
        [(1, "0000000002", "Right"), (8, "0000000003", "Third")],
    )

    output = tmp_path / "union.parquet"
    assert execute_set_operation(left, right, "union", output) == 3
    assert pq.read_table(output).to_pylist() == [
        {"ordinal": 0, "cik_padded": "0000000001", "name": ""},
        {"ordinal": 1, "cik_padded": "0000000002", "name": "Left"},
        {"ordinal": 2, "cik_padded": "0000000003", "name": "Third"},
    ]
    assert (
        execute_set_operation(left, right, "intersect", tmp_path / "both.parquet") == 1
    )
    assert (
        execute_set_operation(left, right, "difference", tmp_path / "only.parquet") == 1
    )


def test_union_falls_back_to_right_name_when_left_is_blank(tmp_path: Path) -> None:
    left = _dataset(tmp_path / "left.parquet", [(0, "0000000001", "")])
    right = _dataset(tmp_path / "right.parquet", [(0, "0000000001", "Fallback")])
    output = tmp_path / "union.parquet"

    assert execute_set_operation(left, right, "union", output) == 1
    assert pq.read_table(output).to_pylist() == [
        {"ordinal": 0, "cik_padded": "0000000001", "name": "Fallback"}
    ]


def test_delta_anti_join_uses_base_cik_and_resets_ordinals(tmp_path: Path) -> None:
    requested = _dataset(
        tmp_path / "requested.parquet",
        [(10, "0000000001", "One"), (20, "0000000002", "Two")],
    )
    pq.write_table(pa.table({"cik": ["0000000001"]}), tmp_path / "base.parquet")
    output = tmp_path / "delta.parquet"

    assert execute_delta_roster(requested, tmp_path / "base.parquet", output) == 1
    assert pq.read_table(output).to_pylist() == [
        {"ordinal": 0, "cik_padded": "0000000002", "name": "Two"}
    ]
    assert pq.read_metadata(tmp_path / "base.parquet").num_rows == 1


def test_diff_report_counts_and_bounds_samples(tmp_path: Path) -> None:
    left = _dataset(
        tmp_path / "left.parquet",
        [(0, "0000000001", "one"), (1, "0000000002", "two")],
    )
    right = _dataset(
        tmp_path / "right.parquet",
        [(0, "0000000002", "two"), (1, "0000000003", "three")],
    )

    report = diff_cohorts(left, right, sample_limit=1)

    assert (report.left_total, report.right_total) == (2, 2)
    assert (report.intersection_count, report.left_only_count) == (1, 1)
    assert (report.right_only_count, report.union_count) == (1, 3)
    assert report.sample_left_only == (("0000000001", "one"),)


def test_expression_parser_and_compiler(tmp_path: Path) -> None:
    tree = parse_expression("(first + second) - third")
    assert isinstance(tree, BinaryOp)
    assert tree.op == "difference"
    assert isinstance(tree.left, BinaryOp)
    assert isinstance(parse_expression("one"), CohortRef)
    assert serialize_expression(tree) == {
        "node": "binary_op",
        "op": "difference",
        "left": {
            "node": "binary_op",
            "op": "union",
            "left": {"node": "cohort_ref", "cohort_identifier": "first"},
            "right": {"node": "cohort_ref", "cohort_identifier": "second"},
        },
        "right": {"node": "cohort_ref", "cohort_identifier": "third"},
    }
    for unsafe in ("run()", "one * two", "one.__class__", "[one]"):
        with pytest.raises(ValueError):
            parse_expression(unsafe)

    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    _register(paths, catalog, "first", "0000000001")
    _register(paths, catalog, "second", "0000000002")
    sql = compile_ast_to_sql(parse_expression("first + second"), catalog)
    with connect() as con:
        rows = con.execute(f"SELECT cik_padded, name FROM ({sql})").fetchall()
    assert rows == [("0000000001", "first"), ("0000000002", "second")]


def test_modulo_sampling_is_deterministic(tmp_path: Path) -> None:
    source = _dataset(
        tmp_path / "source.parquet",
        [
            (0, "0000000001", "A"),
            (1, "0000000002", "B"),
            (2, "0000000003", "C"),
            (3, "0000000004", "D"),
        ],
    )
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    assert sample_cohort(source, first, rate_percent=50) == sample_cohort(
        source, second, rate_percent=50
    )
    assert pq.read_table(first).to_pylist() == pq.read_table(second).to_pylist()


def test_family_sampling_prefers_operating_rows_and_fails_closed(
    tmp_path: Path,
) -> None:
    source = _dataset(
        tmp_path / "source.parquet",
        [
            (0, "0000000001", "A"),
            (1, "0000000002", "B"),
            (2, "0000000003", "C"),
            (3, "0000000004", "D"),
        ],
    )
    family = tmp_path / "family.parquet"
    pq.write_table(
        pa.table(
            {
                "cik": ["0000000001", "0000000002", "0000000003"],
                "company_family": ["shared", "shared", "solo"],
                "family_kind": ["spv", "entity", "entity"],
            }
        ),
        family,
    )
    output = tmp_path / "family-sample.parquet"

    assert (
        sample_cohort(
            source,
            output,
            group_by_family=True,
            family_index_dataset=family,
            rate_percent=100,
        )
        == 3
    )
    assert "0000000002" in pq.read_table(output).column("cik_padded").to_pylist()
    assert "0000000001" not in pq.read_table(output).column("cik_padded").to_pylist()
    with pytest.raises(FamilyIndexNotFoundError):
        sample_cohort(source, tmp_path / "missing.parquet", group_by_family=True)


def test_random_sample_limit_is_seeded(tmp_path: Path) -> None:
    source = _dataset(
        tmp_path / "source.parquet",
        [
            (0, "0000000001", "A"),
            (1, "0000000002", "B"),
            (2, "0000000003", "C"),
            (3, "0000000004", "D"),
        ],
    )
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    sample_cohort(source, first, method="random", sample_limit=2, seed=7)
    sample_cohort(source, second, method="random", sample_limit=2, seed=7)

    assert pq.read_table(first).to_pylist() == pq.read_table(second).to_pylist()
    assert pq.read_metadata(first).num_rows == 2
