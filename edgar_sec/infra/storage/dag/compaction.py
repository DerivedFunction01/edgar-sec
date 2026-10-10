"""Compaction of DAG lineages into consolidated Checkpoint snapshots.

Performs lineage cuts, enforces Parquet contracts, and verifies logical parity.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.infra.storage.dag.paths import PART_PREFIX, PART_SUFFIX
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_identifier,
)
from edgar_sec.infra.storage.parquet import (
    DEFAULT_COMPRESSION,
    read_parquet_key_bounds,
    read_parquet_table,
)

from .catalog import DAGCatalog
from .manifest import DAGNodeManifest, ParentRef, PartDescriptor
from .publication import publish_node
from .resolution import compile_virtual_views, compute_logical_fingerprint
from .spec import RelationSpec
from .traversal import LineageChain, walk_lineage


class CompactionParityError(RuntimeError):
    """Compacted dataset diverged from pre-compaction logical fingerprint."""


def _compact_relation(
    con: object,
    spec: RelationSpec,
    rel_dir: Path,
) -> tuple[PartDescriptor, ...]:
    """Write compacted relation parts applying key-aligned row budgeting."""
    order_cols = ", ".join(sql_identifier(k) for k in spec.sort_order)
    view_name = f"active_{sql_identifier(spec.name)}"
    count_stmt = f"SELECT count(*) FROM {view_name}"
    total_rows = con.execute(count_stmt).fetchone()[0]

    key_col = spec.entity_key or spec.primary_key[0]
    escaped_key = sql_identifier(key_col)
    max_rows = spec.max_rows_per_part

    if total_rows == 0 or max_rows is None or total_rows <= max_rows:
        ranges: list[tuple[str | None, str | None]] = [(None, None)]
    else:
        group_stmt = f"SELECT {escaped_key}, count(*) FROM {view_name} WHERE {escaped_key} IS NOT NULL GROUP BY {escaped_key} ORDER BY {escaped_key}"
        key_counts = con.execute(group_stmt).fetchall()
        ranges = []
        cur_keys: list[str] = []
        cur_cnt = 0
        for k, cnt in key_counts:
            str_k = str(k)
            if cur_cnt > 0 and cur_cnt + cnt > max_rows:
                ranges.append((cur_keys[0], cur_keys[-1]))
                cur_keys = [str_k]
                cur_cnt = cnt
            else:
                cur_keys.append(str_k)
                cur_cnt += cnt
        if cur_keys:
            ranges.append((cur_keys[0], cur_keys[-1]))
        if not ranges:
            ranges = [(None, None)]

    descriptors: list[PartDescriptor] = []
    for idx, (min_k, max_k) in enumerate(ranges):
        part_name = f"{PART_PREFIX}{idx:05d}{PART_SUFFIX}"
        part_path = rel_dir / part_name
        if min_k is None or max_k is None:
            query = f"SELECT * FROM {view_name} ORDER BY {order_cols}"
            params = None
        elif min_k == max_k:
            query = f"SELECT * FROM {view_name} WHERE {escaped_key} = ? ORDER BY {order_cols}"
            params = [min_k]
        else:
            query = f"SELECT * FROM {view_name} WHERE {escaped_key} >= ? AND {escaped_key} <= ? ORDER BY {order_cols}"
            params = [min_k, max_k]

        count = copy_query_to_parquet(
            con,
            query,
            part_path,
            compression=DEFAULT_COMPRESSION,
            params=params,
        )

        k_min, k_max = read_parquet_key_bounds(part_path, key_col)

        descriptors.append(
            PartDescriptor(
                path=f"{spec.name}/{part_name}",
                sha256=file_sha256(part_path),
                row_count=count,
                byte_size=part_path.stat().st_size,
                key_min=k_min,
                key_max=k_max,
            )
        )
    return tuple(descriptors)


def compact_lineage(
    snapshots_root: Path | str,
    specs: Sequence[RelationSpec],
    tip_id: str,
    new_snapshot_id: str,
    staged_dir: Path | str,
    *,
    publish: bool = False,
    branch_name: str | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> DAGNodeManifest:
    """Consolidate DAG lineage into a standalone Checkpoint snapshot."""
    root = Path(snapshots_root)
    staged = Path(staged_dir)
    staged.mkdir(parents=True, exist_ok=True)
    lineage = walk_lineage(root, tip_id)

    con = connect(profile)
    try:
        compile_virtual_views(con, specs, lineage, root)
        pre_fingerprint = compute_logical_fingerprint(con, specs)

        relation_parts: dict[str, tuple[PartDescriptor, ...]] = {}
        for spec in specs:
            rel_dir = staged / spec.name
            rel_dir.mkdir(parents=True, exist_ok=True)
            descriptors = _compact_relation(con, spec, rel_dir)
            relation_parts[spec.name] = descriptors
    finally:
        con.close()

    # Parity verification gate against staged checkpoint
    verify_con = connect(profile)
    try:
        checkpoint_manifest = DAGNodeManifest(
            snapshot_id=new_snapshot_id,
            kind="checkpoint",
            parents=(
                ParentRef(
                    snapshot_id=tip_id,
                    manifest_sha256=DAGCatalog(root).get_manifest_sha256(tip_id) or "",
                ),
            ),
            checkpoint_anchor_id=new_snapshot_id,
            lineage_depth=0,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            relations=relation_parts,
            logical_fingerprint=pre_fingerprint,
        )
        dummy_lineage = LineageChain(
            tip_id=new_snapshot_id,
            checkpoint_anchor_id=new_snapshot_id,
            nodes=(checkpoint_manifest,),
        )
        compile_virtual_views(verify_con, specs, dummy_lineage, staged)
        post_fingerprint = compute_logical_fingerprint(verify_con, specs)
        if post_fingerprint != pre_fingerprint:
            raise CompactionParityError(
                f"compaction parity failure: expected {pre_fingerprint}, got {post_fingerprint}"
            )
    finally:
        verify_con.close()

    if publish:
        publish_node(
            root,
            checkpoint_manifest,
            staged,
            expected_parent_id=tip_id,
            branch_name=branch_name,
        )
    return checkpoint_manifest


__all__ = ["CompactionParityError", "compact_lineage"]
