from __future__ import annotations

import pyarrow.parquet as pq
import pytest

from defs.storage import DuckDBStaging


def test_duckdb_staging_create_insert_export_and_cleanup(tmp_path):
    database = tmp_path / "staging" / "tables.duckdb"
    temp_directory = tmp_path / "spill"
    output = tmp_path / "output" / "data.parquet"

    with DuckDBStaging(
        database,
        threads=1,
        memory_limit="64MB",
        temp_directory=temp_directory,
    ) as staging:
        staging.create_table_as("targets", "SELECT * FROM range(2) AS t(value)")
        staging.insert_query("targets", "SELECT * FROM range(2, 4) AS t(value)")
        assert staging.count("targets") == 4
        assert staging.copy_table("targets", output) == 4
        assert pq.read_table(output).column("value").to_pylist() == [0, 1, 2, 3]

    assert not database.exists()
    assert not database.with_name(database.name + ".wal").exists()


def test_duckdb_staging_rejects_immutable_output(tmp_path):
    output = tmp_path / "data.parquet"
    output.write_bytes(b"existing")
    with DuckDBStaging(tmp_path / "staging.duckdb") as staging:
        staging.create_table_as("targets", "SELECT 1 AS value")
        with pytest.raises(Exception, match="immutable artifact already exists"):
            staging.copy_table("targets", output)
