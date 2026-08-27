from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from defs.storage import (
    And,
    ChunkRange,
    Dataset,
    DatasetSpec,
    DeleteMatching,
    Eq,
    FileStorageExecutor,
    InSet,
    MemoryBackend,
    QueryPlan,
    RunContext,
    SetRecords,
    SortKey,
)
from defs.storage.errors import MalformedArtifact, SchemaMismatchError
from defs.storage.jsonl import JsonlChunkBackend, JsonlKeyValueBackend, JsonlWal
from defs.storage.parquet import ParquetBackend


SCHEMA = pa.schema(
    [
        ("cik", pa.string()),
        ("name", pa.string()),
        ("status", pa.string()),
        (
            "listings",
            pa.list_(pa.struct([("ticker", pa.string()), ("exchange", pa.string())])),
        ),
    ]
)
SPEC = DatasetSpec(
    name="test_records",
    schema_version="1.0.0",
    key_field="cik",
    arrow_schema=SCHEMA,
    required_fields=("cik", "status"),
)
RUN = RunContext(run_id="test")


def record(cik: str, name: str | None = None, status: str = "ok") -> dict:
    return {
        "cik": cik,
        "name": name or cik,
        "status": status,
        "listings": [{"ticker": cik, "exchange": "NYSE"}],
    }


def initialized(backend):
    backend.init(spec=SPEC, run=RUN)
    return backend


@pytest.mark.parametrize("factory", [MemoryBackend])
def test_memory_backend_contract(factory):
    backend = initialized(factory())
    assert backend.set([record("2"), record("1")]) == 2
    assert [
        row["cik"] for row in backend.load(QueryPlan(order_by=(SortKey("cik"),)))
    ] == ["1", "2"]
    assert list(
        backend.load(QueryPlan(predicates=(Eq("status", "ok"),), columns=("cik",)))
    ) == [
        {"cik": "2"},
        {"cik": "1"},
    ]
    assert backend.set([record("1", "updated")]) == 1
    assert (
        list(backend.load(QueryPlan(predicates=(Eq("cik", "1"),))))[0]["name"]
        == "updated"
    )
    assert backend.delete(QueryPlan(predicates=(InSet("cik", ["1"]),))) == 1
    assert (
        backend.delete(QueryPlan(predicates=(And(Eq("status", "ok"), Eq("cik", "2")),)))
        == 1
    )


def test_dataset_validates_before_backend_write():
    dataset = Dataset(MemoryBackend(), SPEC, RUN)
    dataset.init()
    with pytest.raises(SchemaMismatchError):
        dataset.set([{**record("1"), "unknown": True}])
    assert list(dataset.load()) == []
    dataset.close()


def test_jsonl_set_appends_wal_batch_without_loading_canonical_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "records.jsonl"
    backend = initialized(JsonlKeyValueBackend(str(path), max_wal_entries=100))

    def fail_load():
        raise AssertionError("set must not scan the canonical file")

    monkeypatch.setattr(backend, "_load_map", fail_load)
    assert backend.set([record("1"), record("2")]) == 2
    wal_lines = (
        (tmp_path / "records.wal.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(wal_lines) == 2
    assert not path.exists()

    reopened = initialized(JsonlKeyValueBackend(str(path), max_wal_entries=100))
    assert {row["cik"] for row in reopened.load()} == {"1", "2"}
    reopened.set([record("1", "updated")])
    assert (
        list(reopened.load(QueryPlan(predicates=(Eq("cik", "1"),))))[0]["name"]
        == "updated"
    )


def test_jsonl_key_value_compacts_only_at_threshold(tmp_path):
    path = tmp_path / "records.jsonl"
    backend = initialized(JsonlKeyValueBackend(str(path), max_wal_entries=2))
    backend.set([record("1"), record("2")])
    backend.commit()
    assert path.exists()
    assert (tmp_path / "records.wal.jsonl").read_text(encoding="utf-8") == ""
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {line["cik"] for line in lines} == {"1", "2"}


def test_jsonl_wal_ignores_only_truncated_final_line(tmp_path):
    path = tmp_path / "records.jsonl"
    wal_path = tmp_path / "records.wal.jsonl"
    wal_path.write_bytes(
        b'{"op":"set","key":"1","value":{"cik":"1"}}\n{"op":"set","key":"2"'
    )
    replayed = list(JsonlWal(str(path)).replay())
    assert replayed == [{"op": "set", "key": "1", "value": {"cik": "1"}}]

    wal_path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(MalformedArtifact):
        list(JsonlWal(str(path)).replay())


def test_jsonl_chunk_backend_streams_and_finalizes(tmp_path):
    backend = initialized(JsonlChunkBackend(str(tmp_path)))
    chunk = ChunkRange(chunk_id=0, start_row=0, end_row=1)
    ref = backend.write_chunk(chunk, (record(str(i)) for i in range(2)))
    assert ref.row_count == 2
    assert len(backend.load_chunk_records(0)) == 2
    output = tmp_path / "merged.jsonl"
    final = backend.finalize(str(output))
    assert final.row_count == 2
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2


def test_parquet_set_writes_fragment_without_scanning_existing_rows(
    tmp_path, monkeypatch
):
    backend = initialized(ParquetBackend(str(tmp_path)))

    def fail_materialize():
        raise AssertionError("set must not materialize existing fragments")

    monkeypatch.setattr(backend, "_records_from_entries", fail_materialize)
    assert backend.set([record("1")]) == 1
    assert list((tmp_path / "fragments").glob("*.parquet"))
    assert (tmp_path / "test_records-v1.0.0.manifest.json").exists()

    reopened = initialized(ParquetBackend(str(tmp_path)))
    reopened.set([record("1", "updated")])
    rows = list(reopened.load(QueryPlan(predicates=(Eq("cik", "1"),))))
    assert rows[0]["name"] == "updated"
    assert len(reopened._manifest["entries"]) == 2


def test_parquet_chunk_schema_and_merge(tmp_path):
    backend = initialized(ParquetBackend(str(tmp_path)))
    backend.write_chunk(ChunkRange(0, 0, 0), [record("1")])
    backend.write_chunk(ChunkRange(1, 1, 1), [record("2")])
    output = tmp_path / "merged.parquet"
    ref = backend.finalize(str(output))
    assert ref.row_count == 2
    table = pq.read_table(output, schema=SCHEMA)
    assert table.num_rows == 2
    with pytest.raises(SchemaMismatchError):
        backend.write_chunk(ChunkRange(2, 2, 2), [{"cik": "3"}])


@pytest.mark.parametrize(
    "backend_factory",
    [
        lambda tmp: MemoryBackend(),
        lambda tmp: JsonlKeyValueBackend(str(tmp / "records.jsonl")),
        lambda tmp: ParquetBackend(str(tmp)),
    ],
)
def test_file_storage_executor_logical_contract(tmp_path, backend_factory):
    executor = FileStorageExecutor(backend_factory(tmp_path))
    executor.init(SPEC)
    assert executor.set([record("2"), record("1")]) == 2
    assert [
        row["cik"] for row in executor.load(QueryPlan(order_by=(SortKey("cik"),)))
    ] == ["1", "2"]
    assert executor.load_one(QueryPlan(predicates=(Eq("cik", "1"),)))["cik"] == "1"

    executor.transaction(
        [
            SetRecords([record("3")]),
            DeleteMatching(QueryPlan(predicates=(InSet("cik", ["1"]),))),
            SetRecords([record("2", "updated")]),
        ]
    )
    rows = {row["cik"]: row for row in executor.load()}
    assert set(rows) == {"2", "3"}
    assert rows["2"]["name"] == "updated"
    executor.close()


def test_file_storage_executor_transaction_reports_backend_failure(tmp_path):
    executor = FileStorageExecutor(JsonlChunkBackend(str(tmp_path / "chunks_root")))
    executor.init(SPEC)
    from defs.storage import UnsupportedCapability

    with pytest.raises(UnsupportedCapability):
        executor.transaction([SetRecords([record("1")])])
    executor.close()
