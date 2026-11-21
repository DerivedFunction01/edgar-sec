"""DuckDB version-conformance pins: the seam disciplines that keep the code
portable across DuckDB 1.5.6 and 2.0.0, asserted as source and behaviour
checks so a regression fails on either substrate."""

from __future__ import annotations

import re
from pathlib import Path

import warnings

import pyarrow as pa
import pyarrow.parquet as pq

import edgar_sec
from edgar_sec.infra.storage.duckdb import (
    STORAGE_COMPATIBILITY_VERSION,
    arrow_reader,
    arrow_table,
    connect,
    copy_query_to_parquet,
    relation_table,
)

_PACKAGE_ROOT = Path(edgar_sec.__file__).parent
_TESTS_ROOT = Path(__file__).parents[2]
_WRAPPER = _PACKAGE_ROOT / "infra" / "storage" / "duckdb.py"


def _production_sources() -> list[Path]:
    return [
        path for path in _PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in path.parts
    ]


def test_no_direct_duckdb_import_outside_the_wrapper() -> None:
    """The total import ban: only infra/storage/duckdb.py imports duckdb."""
    offenders = sorted(
        str(path.relative_to(_PACKAGE_ROOT))
        for path in _production_sources()
        if path != _WRAPPER
        and re.search(
            r"^\s*(import duckdb|from duckdb import)",
            path.read_text(encoding="utf-8", errors="ignore"),
            re.MULTILINE,
        )
    )
    assert offenders == [], offenders


def test_no_direct_arrow_export_outside_the_wrapper() -> None:
    """Exports go through the infra helpers, never a raw relation call."""
    offenders = sorted(
        str(path.relative_to(_PACKAGE_ROOT))
        for path in _production_sources()
        if path != _WRAPPER
        and (
            ".to_arrow_table(" in path.read_text(encoding="utf-8", errors="ignore")
            or ".to_arrow_reader(" in path.read_text(encoding="utf-8", errors="ignore")
        )
    )
    assert offenders == [], offenders


def test_no_direct_connect_in_tests_outside_the_support_helper() -> None:
    """Tests reach DuckDB only via tests.support.duckdb_connection."""
    offenders = []
    for path in _TESTS_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or path.name == "support.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "duckdb.connect(" in text and re.search(
            r"^\s*import duckdb", text, re.MULTILINE
        ):
            offenders.append(str(path.relative_to(_TESTS_ROOT)))
    assert offenders == [], offenders


def test_no_single_arrow_lambda_remains() -> None:
    """SQL lambdas use the Python form; the single-arrow form is gone in 2.1."""
    pattern = re.compile(r"list_transform\([^)]*\w+ ->")
    offenders = sorted(
        str(path.relative_to(_PACKAGE_ROOT))
        for path in _production_sources()
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    )
    assert offenders == [], offenders


def test_copy_seam_pins_declared_nullability(tmp_path: Path) -> None:
    """Through the seam, a declared NOT NULL schema round-trips identically
    on either version (raw 2.0 COPY and Arrow export both drop it)."""
    schema = pa.schema([("id", pa.int64(), False), ("label", pa.string(), False)])
    target = tmp_path / "pinned.parquet"
    with connect() as con:
        rows = copy_query_to_parquet(
            con,
            "SELECT * FROM (VALUES (1, 'a'), (2, 'b')) AS t(id, label)",
            target,
            schema=schema,
        )
    assert rows == 2
    assert pq.read_schema(target).equals(schema)


def test_helper_export_carries_no_copy_warning(tmp_path: Path) -> None:
    """The relation-form helpers export without the 2.0 DB-API copy warning."""
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        with connect() as con:
            table = arrow_table(con, "SELECT 1 AS value")
            reader = arrow_reader(con, "SELECT 2 AS value")
            assert [batch.num_rows for batch in reader] == [1]
    assert table.to_pylist() == [{"value": 1}]
    assert not [warning for warning in recorded if "extra copy" in str(warning.message)]


def test_helpers_after_bare_execute_with_unfinished_result() -> None:
    """Bare execute() DDL plus a fetchone() aggregate leaves an unfinished
    result; the helpers drain it and still see the temp objects (2.0)."""
    with connect() as con:
        con.execute("CREATE TEMP TABLE staged (value INTEGER)")
        con.execute("INSERT INTO staged VALUES (1), (2)")
        con.execute("CREATE OR REPLACE TEMP VIEW staged_view AS SELECT * FROM staged")
        assert con.execute("SELECT count(*) FROM staged").fetchone()[0] == 2
        table = arrow_table(con, "SELECT value FROM staged_view ORDER BY value")
        assert table.to_pylist() == [{"value": 1}, {"value": 2}]
        assert con.execute("SELECT count(*) FROM staged").fetchone()[0] == 2
        reader = arrow_reader(con, "SELECT value FROM staged ORDER BY value")
        assert reader.read_all().to_pylist() == [{"value": 1}, {"value": 2}]


def test_relation_table_after_bare_execute_with_unfinished_result() -> None:
    """A relation built before a bare execute() left its result unfinished
    still materializes through relation_table (the check fires at execution)."""
    with connect() as con:
        con.execute("CREATE TEMP TABLE staged (value INTEGER)")
        con.execute("INSERT INTO staged VALUES (3)")
        relation = con.sql("SELECT value FROM staged")
        assert con.execute("SELECT count(*) FROM staged").fetchone()[0] == 1
        assert relation_table(relation).to_pylist() == [{"value": 3}]


def test_python_lambda_form_executes() -> None:
    """The Python-style lambda runs the ticker match on either version."""
    with connect() as con:
        row = con.execute(
            "SELECT list_transform(['a', 'b'], lambda x: upper(x))"
        ).fetchone()
    assert row[0] == ["A", "B"]


def test_file_database_is_written_at_the_pinned_compatibility(
    tmp_path: Path,
) -> None:
    """connect() writes file databases at the 1.5 storage line."""
    database = tmp_path / "pinned.duckdb"
    with connect(database=database) as con:
        con.execute("CREATE TABLE probe (value INTEGER)")
        setting = con.execute(
            "SELECT current_setting('storage_compatibility_version')"
        ).fetchone()[0]
    assert setting == STORAGE_COMPATIBILITY_VERSION == "v1.5.0"
    with connect(database=database) as con:
        assert con.execute("SELECT count(*) FROM probe").fetchone()[0] == 0
