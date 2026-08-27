"""Shared fixtures for viewer tests: genuine artifacts in a temp workspace."""

from pathlib import Path

import pyarrow as pa
import pytest
from pyarrow import parquet

from defs.storage.jsonl import write_records_atomic
from defs.viewer.discover import artifact_id


def base64_id(relative: str) -> str:
    return artifact_id(relative)


def write_parquet(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parquet.write_table(table, str(path))


@pytest.fixture()
def artifacts_root(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    root.mkdir()
    return root


@pytest.fixture()
def chunk_dataset(artifacts_root: Path):
    """A partition chunk written as NDJSON via the shared storage writer."""
    relative = Path(
        "metadata/runs/run-1/partitions/partition-00001/chunks/chunk-00001.jsonl"
    )
    path = artifacts_root / relative
    records = [
        {
            "cik": "0000000020",
            "name": "K TRON",
            "status": "ok",
            "filings": [{"accession": "0000000020-26-000001", "form": "10-K"}],
        },
        {
            "cik": "0000001761",
            "name": "TRANZONIC",
            "status": "failed",
            "filings": [],
        },
        {
            "cik": "0000037996",
            "name": "FORD MOTOR CO",
            "status": "ok",
            "filings": [
                {"accession": "0000037996-25-000009", "form": "10-K"},
                {"accession": "0000037996-24-000004", "form": "10-K/A"},
            ],
        },
    ]
    write_records_atomic(records, str(path))
    return {
        "id": artifact_id(relative),
        "relative": relative,
        "path": path,
        "records": records,
    }


@pytest.fixture()
def parquet_dataset(artifacts_root: Path):
    """A canonical-style parquet artifact including a nested column."""
    relative = Path("metadata/canonical/submission_metadata.parquet")
    path = artifacts_root / relative
    table = pa.table(
        {
            "cik": pa.array(["0000000020", "0000001761"]),
            "status": pa.array(["ok", "ok"]),
            "filings": pa.array(
                [
                    [{"form": "10-K", "file_count": 3}],
                    [{"form": "10-K", "file_count": 1}],
                ],
                type=pa.list_(
                    pa.struct(
                        [
                            pa.field("form", pa.string()),
                            pa.field("file_count", pa.int64()),
                        ]
                    )
                ),
            ),
        }
    )
    write_parquet(path, table)
    return {"id": artifact_id(relative), "relative": relative, "path": path}
