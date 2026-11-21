"""Tests for pre-publish candidate anti-join and no-op elision."""

from pathlib import Path

import pyarrow as pa

from edgar_sec.infra.storage.dag.anti_join import filter_candidate_delta
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.duckdb import connect

SCHEMA = pa.schema([("id", pa.string()), ("status", pa.string())])


def test_anti_join_noop_and_delta(tmp_path: Path) -> None:
    specs = (
        RelationSpec(
            name="items",
            schema=SCHEMA,
            primary_key=("id",),
            merge_strategy="upsert",
            sort_order=("id",),
        ),
    )

    con = connect()
    try:
        # Existing active view has ("1", "done")
        con.execute(
            "CREATE TEMP VIEW active_items AS SELECT '1' AS id, 'done' AS status"
        )

        # Candidate A: exact identical duplicate
        con.execute("CREATE TEMP TABLE cand_noop AS SELECT '1' AS id, 'done' AS status")
        res_noop = filter_candidate_delta(
            con,
            specs,
            candidate_tables={"items": "cand_noop"},
            active_views={"items": "active_items"},
            output_dir=tmp_path / "noop",
        )
        assert res_noop.is_noop is True
        assert len(res_noop.filtered_parts) == 0

        # Candidate B: one identical, one new item ("2", "pending")
        con.execute(
            "CREATE TEMP TABLE cand_partial AS "
            "SELECT '1' AS id, 'done' AS status UNION ALL "
            "SELECT '2' AS id, 'pending' AS status"
        )
        res_partial = filter_candidate_delta(
            con,
            specs,
            candidate_tables={"items": "cand_partial"},
            active_views={"items": "active_items"},
            output_dir=tmp_path / "partial",
        )
        assert res_partial.is_noop is False
        assert "items" in res_partial.filtered_parts
        assert res_partial.row_counts["items"] == 1
    finally:
        con.close()
