"""Tests for the snapshot SQL console."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.console import (
    SnapshotQueryError,
    SnapshotQuerySession,
    validate_snapshot_query,
)
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.parquet import write_parquet_table

SCHEMA = pa.schema([("id", pa.string()), ("value", pa.int64())])
SPEC = RelationSpec(
    name="records",
    schema=SCHEMA,
    primary_key=("id",),
    merge_strategy="upsert",
    sort_order=("id",),
)


def _publish(root: Path, snapshot_id: str, values: list[int]) -> None:
    snapshot_dir = root / snapshot_id
    snapshot_dir.mkdir(parents=True)
    part = snapshot_dir / "records.parquet"
    table = pa.table(
        {"id": [str(index) for index in range(len(values))], "value": values},
        schema=SCHEMA,
    )
    write_parquet_table(table, part)
    manifest = DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id=snapshot_id,
        lineage_depth=0,
        created_at="2026-10-12T00:00:00Z",
        relations={
            "records": (
                PartDescriptor(
                    path="records.parquet",
                    sha256=file_sha256(part),
                    row_count=len(values),
                    byte_size=part.stat().st_size,
                ),
            ),
        },
        logical_fingerprint=f"fp-{snapshot_id}",
    )
    DAGCatalog(root).publish_node(manifest, branch_name="main")


def _session(root: Path, *, page_size: int = 2) -> SnapshotQuerySession:
    return SnapshotQuerySession(root, (SPEC,), page_size=page_size)


def test_session_pins_current_snapshot_when_pointer_advances(tmp_path: Path) -> None:
    _publish(tmp_path, "first", [1])
    session = _session(tmp_path)
    try:
        _publish(tmp_path, "second", [2])
        assert session.snapshot_id == "first"
        assert session.execute("SELECT value FROM active_records").rows == ((1,),)
    finally:
        session.close()


def test_query_results_page_and_materialize_for_session(tmp_path: Path) -> None:
    _publish(tmp_path, "first", [10, 20, 30])
    with _session(tmp_path, page_size=2) as session:
        first = session.execute("SELECT value FROM active_records ORDER BY id")
        assert first.rows == ((10,), (20,))
        assert first.has_more
        assert session.next_page().rows == ((30,),)
        assert not session.next_page().has_more

        session.execute("SELECT value FROM active_records ORDER BY id")
        assert session.materialize("picked") == "console_picked"
        assert session.execute("SELECT * FROM console_picked").rows == (
            (10,),
            (20,),
        )


def test_saved_sql_is_reloaded_and_validated_on_execution(tmp_path: Path) -> None:
    _publish(tmp_path, "first", [1])
    with _session(tmp_path) as session:
        path = session.save_query("sample", "SELECT value FROM active_records")
        assert session.list_queries() == ("sample",)
        path.write_text(
            "SELECT value FROM read_parquet('/etc/passwd')", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="only snapshot relations"):
            session.execute(session.load_query("sample"))
        assert session.delete_query("sample")
        assert not session.delete_query("sample")


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE records",
        "SELECT * FROM read_parquet('/tmp/other.parquet')",
        "SELECT * FROM '/tmp/other.parquet'",
    ],
)
def test_query_policy_refuses_writes_and_external_sources(query: str) -> None:
    with pytest.raises(ValueError):
        validate_snapshot_query(query)


def test_query_policy_allows_path_text_and_comments(tmp_path: Path) -> None:
    _publish(tmp_path, "first", [1])
    query = (
        "SELECT '/tmp/not-a-source' AS note FROM active_records -- read_parquet('/x')"
    )
    with _session(tmp_path) as session:
        assert session.execute(query).rows == (("/tmp/not-a-source",),)
    assert validate_snapshot_query("SELECT 'FROM ''/tmp/file''' AS note")


def test_preflight_and_parquet_export(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    _publish(root, "first", [1, 2, 3])
    destination = tmp_path / "console-export.parquet"
    with _session(root) as session:
        plan = session.preflight("SELECT value FROM active_records")
        assert plan.rows
        session.execute("SELECT value FROM active_records")
        assert session.export_parquet(destination) == 3
    assert pq.read_table(destination).num_rows == 3


def test_export_is_rejected_inside_snapshot_repository(tmp_path: Path) -> None:
    _publish(tmp_path, "first", [1])
    with _session(tmp_path) as session:
        session.execute("SELECT value FROM active_records")
        with pytest.raises(ValueError, match="inside the snapshot repository"):
            session.export_parquet(tmp_path / "result.parquet")


def test_session_requires_current_pointer(tmp_path: Path) -> None:
    DAGCatalog(tmp_path)
    with pytest.raises(SnapshotQueryError, match="no current snapshot"):
        _session(tmp_path)
