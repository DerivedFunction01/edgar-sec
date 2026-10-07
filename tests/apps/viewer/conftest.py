"""A synthetic artifacts tree in the shapes the pipelines actually write, so
discovery is not exercised against a convenient approximation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.pipelines.document_storage.manifests import (
    PART_KIND_INDEX,
    PART_KIND_PAYLOAD,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    CATALOG_SNAPSHOT_MANIFEST_NAME,
    SNAPSHOT_FILE_NAME,
    TARGETS_DIR_NAME,
    FilingCatalogPaths,
)
from edgar_sec.pipelines.metadata_sync.paths import (
    METADATA_DIR,
    MetadataPaths,
)

_INDEX_SCHEMA = pa.schema(
    [
        pa.field("doc_id", pa.string()),
        pa.field("source_cik", pa.int64()),
        pa.field("form", pa.string()),
    ]
)
_PAYLOAD_SCHEMA = pa.schema(
    [
        pa.field("doc_id", pa.string()),
        pa.field("raw_payload", pa.binary()),
    ]
)
_PROFILE_SCHEMA = pa.schema(
    [
        pa.field("cik", pa.int64()),
        pa.field("name", pa.string()),
    ]
)
_TARGET_SCHEMA = pa.schema(
    [
        pa.field("accession_number", pa.string()),
        pa.field("form", pa.string()),
    ]
)
_CIK_SCHEMA = pa.schema([pa.field("cik", pa.int64())])


def _write(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _sha256(path: Path) -> str:
    from edgar_sec.foundation.hashing import file_sha256

    return file_sha256(path)


def build_metadata_snapshot(
    root: Path, snapshot_id: str = "snap-meta", part_count: int = 2
) -> Path:
    """Publish a multipart submissions snapshot with a CIK index."""
    paths = MetadataPaths(artifacts_root=root)
    snapshot_dir = paths.snapshot_dir(snapshot_id)
    parts: list[dict[str, object]] = []
    for index in range(part_count):
        part_path = paths.snapshot_part(snapshot_id, f"part-{index:05d}.parquet")
        _write(
            part_path,
            pa.table(
                {
                    "cik": pa.array([1000 + index, 2000 + index], pa.int64()),
                    "name": pa.array([f"CO {index}", f"INC {index}"], pa.string()),
                },
                schema=pa.schema(
                    [pa.field("cik", pa.int64()), pa.field("name", pa.string())]
                ),
            ),
        )
        parts.append(
            {
                "path": str(part_path.relative_to(snapshot_dir)),
                "sha256": _sha256(part_path),
                "row_count": 2,
                "source": f"chunk-{index:05d}",
            }
        )
    index_path = paths.snapshot_cik_index(snapshot_id)
    _write(
        index_path,
        pa.table({"cik": pa.array([1000, 2000], pa.int64())}, schema=_CIK_SCHEMA),
    )
    manifest = {
        "snapshot_id": snapshot_id,
        "manifest_version": "2.0.0",
        "sort_order": "chunk_order",
        "output_path": "",
        "artifact_sha256": "",
        "cik_index_path": str(index_path.relative_to(snapshot_dir)),
        "cik_index_sha256": _sha256(index_path),
        "cik_count": 2,
        "row_count": 2 * part_count,
        "chunk_count": part_count,
        "part_count": part_count,
        "plan_id": "plan-meta",
        "schema_version": "1",
        "parts": parts,
    }
    manifest_path = paths.snapshot_manifest(snapshot_id)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def build_catalog_snapshot(root: Path, catalog_id: str = "cat-1") -> Path:
    """Publish a filing catalog with profiles and two target shards."""
    paths = FilingCatalogPaths(artifacts_root=root)
    snapshot_dir = paths.snapshot_dir(catalog_id)
    _write(
        snapshot_dir / SNAPSHOT_FILE_NAME,
        pa.table(
            {
                "cik": pa.array([1000, 2000], pa.int64()),
                "name": pa.array(["CO A", "CO B"], pa.string()),
            },
            schema=_PROFILE_SCHEMA,
        ),
    )
    targets_dir = snapshot_dir / TARGETS_DIR_NAME
    for index in range(2):
        _write(
            targets_dir / f"part-{index:05d}.parquet",
            pa.table(
                {
                    "accession_number": pa.array([f"0000-0{index}-1"], pa.string()),
                    "form": pa.array(["10-K"], pa.string()),
                },
                schema=_TARGET_SCHEMA,
            ),
        )
    manifest = {
        "manifest_kind": "filing_catalog_snapshot",
        "catalog_id": catalog_id,
        "snapshot_id": f"catalog-{catalog_id}",
        "profile_row_count": 2,
        "target_row_count": 2,
        "schema_version": "1",
        "source_part_count": 1,
    }
    manifest_path = snapshot_dir / CATALOG_SNAPSHOT_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def build_document_snapshot(root: Path, snapshot_id: str = "doc-1") -> Path:
    """Publish a document snapshot with index and payload parts."""
    snapshots_root = root / "document_storage" / "snapshots"
    snapshot_dir = snapshots_root / snapshot_id
    index_path = snapshot_dir / "index" / "index-0000.parquet"
    payload_path = snapshot_dir / "payload" / "payload-0000.parquet"
    _write(
        index_path,
        pa.table(
            {
                "doc_id": pa.array(["d1", "d2"], pa.string()),
                "source_cik": pa.array([1000, 2000], pa.int64()),
                "form": pa.array(["10-K", "10-Q"], pa.string()),
            },
            schema=_INDEX_SCHEMA,
        ),
    )
    _write(
        payload_path,
        pa.table(
            {
                "doc_id": pa.array(["d1", "d2"], pa.string()),
                "raw_payload": pa.array(
                    [b"<html>a</html>", b"<html>b</html>"], pa.binary()
                ),
            },
            schema=_PAYLOAD_SCHEMA,
        ),
    )
    manifest = {
        "snapshot_id": snapshot_id,
        "run_id": "run-doc",
        "schema_version": "1",
        "resolved_parts": [
            {
                "path": str(index_path.relative_to(snapshot_dir)),
                "kind": PART_KIND_INDEX,
                "doc_ids": ["d1", "d2"],
                "row_count": 2,
                "byte_size": index_path.stat().st_size,
            },
            {
                "path": str(payload_path.relative_to(snapshot_dir)),
                "kind": PART_KIND_PAYLOAD,
                "doc_ids": ["d1", "d2"],
                "row_count": 2,
                "byte_size": payload_path.stat().st_size,
            },
        ],
    }
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def build_transient_run(
    root: Path, run_id: str = "run-1", chunk_count: int = 3
) -> Path:
    """Write chunk files for an in-flight run that has no manifest yet."""
    run_dir = root / "transient" / METADATA_DIR / "runs" / run_id
    for index in range(chunk_count):
        _write(
            run_dir / f"chunk-{index:05d}.parquet",
            pa.table(
                {
                    "cik": pa.array([3000 + index], pa.int64()),
                    "name": pa.array([f"CHUNK {index}"], pa.string()),
                },
                schema=pa.schema(
                    [pa.field("cik", pa.int64()), pa.field("name", pa.string())]
                ),
            ),
        )
    return run_dir


def build_sqlite_database(root: Path, name: str = "store.db") -> Path:
    """Write a small SQLite database with one user table."""
    import sqlite3

    path = root / "document_storage" / "fixtures" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE payloads (doc_id TEXT, body BLOB)")
        conn.execute("INSERT INTO payloads VALUES ('d1', ?)", (b"x",))
        conn.commit()
    finally:
        conn.close()
    return path


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def artifacts_root(tmp_path: Path) -> Path:
    """An empty artifacts root to publish into."""
    root = tmp_path / "artifacts"
    root.mkdir()
    return root


@pytest.fixture
def metadata_tree(artifacts_root: Path) -> Path:
    """A root with one published multipart submissions snapshot."""
    build_metadata_snapshot(artifacts_root)
    return artifacts_root


@pytest.fixture
def catalog_tree(artifacts_root: Path) -> Path:
    """A root with one published filing catalog."""
    build_catalog_snapshot(artifacts_root)
    return artifacts_root


@pytest.fixture
def document_tree(artifacts_root: Path) -> Path:
    """A root with one published document snapshot."""
    build_document_snapshot(artifacts_root)
    return artifacts_root


@pytest.fixture
def transient_tree(artifacts_root: Path) -> Path:
    """A root with an in-flight run that has no manifest."""
    build_transient_run(artifacts_root)
    return artifacts_root


@pytest.fixture
def sqlite_tree(artifacts_root: Path) -> Path:
    """A root with a SQLite payload store."""
    build_sqlite_database(artifacts_root)
    return artifacts_root


@pytest.fixture
def full_tree(
    artifacts_root: Path,
) -> Callable[[Path], Path]:
    """A factory that publishes every dataset type into one root."""

    def build(root: Path) -> Path:
        build_metadata_snapshot(root)
        build_catalog_snapshot(root)
        build_document_snapshot(root)
        build_transient_run(root)
        build_sqlite_database(root)
        return root

    return build
