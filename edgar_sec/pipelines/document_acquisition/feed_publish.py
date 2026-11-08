"""DAG publication of the Feed-archives inventory relation.

Publication follows the ledger idiom: a DuckDB anti-join against the
branch tip's active parts drops bundles already published, so a re-run
over a stored day publishes nothing.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.anti_join import filter_candidate_delta
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    ordered_parts_fingerprint,
)
from edgar_sec.infra.storage.dag.publication import publish_node, read_pointer
from edgar_sec.infra.storage.duckdb import connect, sql_path_list
from edgar_sec.infra.storage.parquet import read_parquet_table, write_parquet_table

from .feed_inventory import FeedInventoryRecord
from .paths import AcquisitionPaths
from .snapshot.schema import SNAPSHOT_SCHEMA_VERSION
from .snapshot.specs import FEED_INVENTORY_SPEC

FEED_INVENTORY_FILE = "part-00000.parquet"
_CANDIDATE_TABLE = "candidate_feed_inventory"
_ACTIVE_VIEW = "active_feed_inventory"


@dataclass(frozen=True, slots=True)
class FeedPublishResult:
    """Outcome of one inventory publish attempt against the branch tip."""

    published: bool
    snapshot_id: str | None
    tip_before: str | None
    new_rows: int
    total_rows: int


def feed_tip(paths: AcquisitionPaths, branch: str) -> str | None:
    """The branch tip snapshot id, or ``None`` when nothing is published."""
    if not paths.catalog_file.is_file():
        return None
    pointer = read_pointer(paths.snapshots_root, branch)
    return str(pointer["snapshot_id"]) if pointer else None


def active_part_paths(
    paths: AcquisitionPaths, tip_snapshot_id: str
) -> tuple[Path, ...]:
    """Active feed-inventory parts of the tip lineage, ancestor to tip."""
    catalog = DAGCatalog(paths.snapshots_root, read_only=True)
    return catalog.resolve_active_relation(
        tip_snapshot_id, FEED_INVENTORY_SPEC.name, relative_to=paths.snapshots_root
    )


def published_archive_shas(paths: AcquisitionPaths, branch: str) -> frozenset[str]:
    """Archive SHAs already carried by the branch's published inventory."""
    tip = feed_tip(paths, branch)
    if tip is None:
        return frozenset()
    shas: set[str] = set()
    for part in active_part_paths(paths, tip):
        table = read_parquet_table(part)
        shas.update(str(value) for value in table.column("archive_sha256").to_pylist())
    return frozenset(shas)


def inventory_rows(
    records: Sequence[FeedInventoryRecord],
    *,
    snapshot_id: str,
    fetched_at: datetime,
) -> list[dict[str, object]]:
    """Expand inventory records into relation rows for one snapshot."""
    return [
        {
            "accession": record.accession,
            "cik": record.cik,
            "form": record.form,
            "filing_date": record.filing_date,
            "feed_date": record.feed_date,
            "bundle_id": record.bundle_id,
            "archive_sha256": record.archive_sha256,
            "snapshot_id": snapshot_id,
            "fetched_at": fetched_at.isoformat(),
        }
        for record in records
    ]


def derive_snapshot_id(
    records: Sequence[FeedInventoryRecord], *, parent_id: str | None, command: str
) -> str:
    """Content identity for a publish: parent, command, and bundle keys."""
    keys = sorted({(record.archive_sha256, record.bundle_id) for record in records})
    fingerprint = sha256_text(
        canonical_json({"parent": parent_id or "", "command": command, "keys": keys})
    )
    return f"feed-{fingerprint[:24]}"


def publish_inventory(
    paths: AcquisitionPaths,
    records: Sequence[FeedInventoryRecord],
    *,
    branch: str,
    fetched_at: datetime,
    command: str = "feed-ingest",
) -> FeedPublishResult:
    """Publish one batch of inventory records as the next branch snapshot."""
    tip = feed_tip(paths, branch)
    snapshot_id = derive_snapshot_id(records, parent_id=tip, command=command)
    rows = inventory_rows(records, snapshot_id=snapshot_id, fetched_at=fetched_at)
    staging = paths.feed_staging_root / snapshot_id
    staging.mkdir(parents=True, exist_ok=True)
    candidate_file = staging / "candidate.parquet"
    write_parquet_table(
        pa.Table.from_pylist(rows, schema=FEED_INVENTORY_SPEC.schema), candidate_file
    )

    con = connect()
    try:
        con.execute(
            "CREATE TEMP TABLE candidate_feed_inventory AS "
            f"SELECT * FROM read_parquet({sql_path_list([str(candidate_file)])})"
        )
        total_before = _stage_active_view(con, paths, tip)
        filtered = filter_candidate_delta(
            con,
            (FEED_INVENTORY_SPEC,),
            {FEED_INVENTORY_SPEC.name: _CANDIDATE_TABLE},
            {FEED_INVENTORY_SPEC.name: _ACTIVE_VIEW},
            staging / "filtered",
        )
        if filtered.is_noop:
            return FeedPublishResult(
                published=False,
                snapshot_id=None,
                tip_before=tip,
                new_rows=0,
                total_rows=total_before,
            )
        new_rows = filtered.row_counts[FEED_INVENTORY_SPEC.name]
    finally:
        con.close()

    staged_dir = staging / "snapshot"
    relation_dir = staged_dir / FEED_INVENTORY_SPEC.name
    relation_dir.mkdir(parents=True, exist_ok=True)
    part_file = relation_dir / FEED_INVENTORY_FILE
    shutil.copyfile(filtered.filtered_parts[FEED_INVENTORY_SPEC.name], part_file)
    descriptor = PartDescriptor(
        path=f"{snapshot_id}/{FEED_INVENTORY_SPEC.name}/{FEED_INVENTORY_FILE}",
        sha256=file_sha256(part_file),
        row_count=new_rows,
        byte_size=part_file.stat().st_size,
    )
    manifest = _manifest(paths, snapshot_id, tip, descriptor, command, fetched_at)
    publish_node(
        paths.snapshots_root,
        manifest,
        staged_dir=staged_dir,
        expected_parent_id=tip,
        branch_name=branch,
    )
    return FeedPublishResult(
        published=True,
        snapshot_id=snapshot_id,
        tip_before=tip,
        new_rows=new_rows,
        total_rows=total_before + new_rows,
    )


def _stage_active_view(con, paths: AcquisitionPaths, tip: str | None) -> int:
    """Materialize the tip's active inventory as a view; return its count."""
    if tip is None:
        con.execute(
            "CREATE TEMP VIEW active_feed_inventory AS "
            "SELECT * FROM candidate_feed_inventory WHERE false"
        )
        return 0
    parts = active_part_paths(paths, tip)
    con.execute(
        "CREATE TEMP VIEW active_feed_inventory AS "
        f"SELECT * FROM read_parquet({sql_path_list([str(p) for p in parts])})"
    )
    return int(con.execute("SELECT count(*) FROM active_feed_inventory").fetchone()[0])


def _manifest(
    paths: AcquisitionPaths,
    snapshot_id: str,
    tip: str | None,
    descriptor: PartDescriptor,
    command: str,
    fetched_at: datetime,
) -> DAGNodeManifest:
    parents: tuple[ParentRef, ...] = ()
    anchor = snapshot_id
    depth = 0
    if tip is not None:
        catalog = DAGCatalog(paths.snapshots_root, read_only=True)
        parent = catalog.get_manifest(tip)
        parents = (
            ParentRef(
                snapshot_id=tip,
                manifest_sha256=catalog.get_manifest_sha256(tip) or "",
            ),
        )
        if parent is not None:
            anchor = parent.checkpoint_anchor_id or tip
            depth = parent.lineage_depth + 1
    return DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="delta" if tip is not None else "checkpoint",
        parents=parents,
        checkpoint_anchor_id=anchor,
        lineage_depth=depth,
        created_at=fetched_at.isoformat(),
        relations={FEED_INVENTORY_SPEC.name: (descriptor,)},
        logical_fingerprint=ordered_parts_fingerprint([descriptor.sha256]),
        schema_versions={FEED_INVENTORY_SPEC.name: str(SNAPSHOT_SCHEMA_VERSION)},
        metadata={"command": command, "fetched_at": fetched_at.isoformat()},
    )


__all__ = [
    "FeedPublishResult",
    "active_part_paths",
    "derive_snapshot_id",
    "feed_tip",
    "inventory_rows",
    "publish_inventory",
    "published_archive_shas",
]
