"""Relational catalog for DAG snapshot nodes, parts, branches, and tags.

Replaces multi-file JSON directory trees with an embedded SQLite catalog in WAL mode.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.paths import CATALOG_DB_NAME
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    NodeKind,
    ParentRef,
    PartDescriptor,
)


_INIT_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA page_size = 8192;

CREATE TABLE IF NOT EXISTS nodes (
    snapshot_id          TEXT PRIMARY KEY,
    kind                 TEXT NOT NULL CHECK (kind IN ('delta', 'checkpoint')),
    parent_id            TEXT,
    checkpoint_anchor_id TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    lineage_depth        INTEGER NOT NULL CHECK (lineage_depth >= 0),
    manifest_sha256      TEXT NOT NULL,
    logical_fingerprint  TEXT NOT NULL DEFAULT '',
    schema_versions_json TEXT NOT NULL DEFAULT '{}',
    metadata_json        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_anchor ON nodes(checkpoint_anchor_id);
CREATE INDEX IF NOT EXISTS idx_nodes_depth  ON nodes(lineage_depth);

CREATE TABLE IF NOT EXISTS node_parents (
    snapshot_id          TEXT NOT NULL REFERENCES nodes(snapshot_id) ON DELETE CASCADE,
    parent_id            TEXT NOT NULL,
    parent_order         INTEGER NOT NULL DEFAULT 0,
    parent_sha256        TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, parent_id)
);
CREATE INDEX IF NOT EXISTS idx_node_parents_parent ON node_parents(parent_id);

CREATE TABLE IF NOT EXISTS parts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id          TEXT NOT NULL REFERENCES nodes(snapshot_id) ON DELETE CASCADE,
    relation_name        TEXT NOT NULL,
    part_path            TEXT NOT NULL,
    row_count            INTEGER NOT NULL,
    byte_size            INTEGER NOT NULL,
    sha256               TEXT NOT NULL,
    min_value            TEXT,
    max_value            TEXT
);
CREATE INDEX IF NOT EXISTS idx_parts_snap_rel ON parts(snapshot_id, relation_name);
CREATE INDEX IF NOT EXISTS idx_parts_range    ON parts(relation_name, min_value, max_value);
CREATE INDEX IF NOT EXISTS idx_parts_path     ON parts(part_path);

CREATE TABLE IF NOT EXISTS branches (
    name                 TEXT PRIMARY KEY,
    snapshot_id          TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    name                 TEXT PRIMARY KEY,
    snapshot_id          TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    message              TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS catalog_meta (
    key                  TEXT PRIMARY KEY,
    value                TEXT NOT NULL
);
"""


class DAGCatalog:
    """Embedded SQLite catalog managing DAG snapshot metadata."""

    def __init__(self, snapshots_root: Path | str, *, read_only: bool = False) -> None:
        self.snapshots_root = Path(snapshots_root)
        self.catalog_file = self.snapshots_root / CATALOG_DB_NAME
        self.read_only = read_only
        if read_only:
            if not self.catalog_file.is_file():
                raise FileNotFoundError(self.catalog_file)
        else:
            self.snapshots_root.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    @classmethod
    def find_snapshot_ids_by_metadata(
        cls, snapshots_root: Path | str, key: str, value: str
    ) -> tuple[str, ...]:
        catalog_file = Path(snapshots_root) / CATALOG_DB_NAME
        if not catalog_file.is_file():
            return ()
        uri = f"{catalog_file.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as con:
            rows = con.execute(
                "SELECT snapshot_id, metadata_json FROM nodes ORDER BY snapshot_id"
            )
            matches = []
            for snapshot_id, metadata_json in rows:
                metadata = json.loads(metadata_json or "{}")
                if isinstance(metadata, dict) and metadata.get(key) == value:
                    matches.append(str(snapshot_id))
        return tuple(matches)

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            uri = f"{self.catalog_file.resolve().as_uri()}?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=30.0)
        else:
            con = sqlite3.connect(str(self.catalog_file), timeout=30.0)
            con.execute("PRAGMA journal_mode = WAL;")
            con.execute("PRAGMA synchronous = NORMAL;")
            con.execute("PRAGMA foreign_keys = ON;")
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.executescript(_INIT_SCHEMA_SQL)

    def publish_node(
        self, manifest: DAGNodeManifest, branch_name: str = "main"
    ) -> None:
        """Atomically record a snapshot node and update the branch pointer."""
        now_iso = datetime.now(UTC).isoformat()
        with self._connect() as con:
            self._insert_manifest(con, manifest)
            con.execute(
                """
                INSERT INTO branches (name, snapshot_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    snapshot_id = excluded.snapshot_id,
                    updated_at = excluded.updated_at
                """,
                (branch_name, manifest.snapshot_id, now_iso),
            )

    def record_node(self, manifest: DAGNodeManifest) -> None:
        """Atomically record a snapshot node without changing branch pointers."""
        with self._connect() as con:
            self._insert_manifest(con, manifest)

    def _insert_manifest(
        self, con: sqlite3.Connection, manifest: DAGNodeManifest
    ) -> None:
        payload = canonical_json(manifest.to_dict())
        digest = sha256_text(payload)

        cur = con.execute(
            "SELECT manifest_sha256, logical_fingerprint FROM nodes WHERE snapshot_id = ?",
            (manifest.snapshot_id,),
        )
        existing = cur.fetchone()
        if existing is not None:
            if existing["manifest_sha256"] == digest or (
                existing["logical_fingerprint"]
                and existing["logical_fingerprint"] == manifest.logical_fingerprint
            ):
                return
            raise ValueError(
                f"snapshot {manifest.snapshot_id!r} already recorded with different digest"
            )

        parent_id = manifest.parent_snapshot_id or None
        schema_json = json.dumps(dict(manifest.schema_versions), sort_keys=True)
        meta_json = json.dumps(dict(manifest.metadata), sort_keys=True)

        con.execute(
            """
            INSERT INTO nodes (
                snapshot_id, kind, parent_id, checkpoint_anchor_id,
                created_at, lineage_depth, manifest_sha256,
                logical_fingerprint, schema_versions_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                manifest.snapshot_id,
                manifest.kind,
                parent_id,
                manifest.checkpoint_anchor_id,
                manifest.created_at,
                manifest.lineage_depth,
                digest,
                manifest.logical_fingerprint,
                schema_json,
                meta_json,
            ),
        )

        for idx, pref in enumerate(manifest.parents):
            con.execute(
                """
                INSERT INTO node_parents (snapshot_id, parent_id, parent_order, parent_sha256)
                VALUES (?, ?, ?, ?)
                """,
                (manifest.snapshot_id, pref.snapshot_id, idx, pref.manifest_sha256),
            )

        part_rows: list[tuple[Any, ...]] = []
        for rel_name, parts in manifest.relations.items():
            for part in parts:
                part_rows.append(
                    (
                        manifest.snapshot_id,
                        rel_name,
                        part.path,
                        part.row_count,
                        part.byte_size,
                        part.sha256,
                        part.key_min,
                        part.key_max,
                    )
                )

        if part_rows:
            con.executemany(
                """
                INSERT INTO parts (
                    snapshot_id, relation_name, part_path,
                    row_count, byte_size, sha256, min_value, max_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                part_rows,
            )

    def get_manifest(self, snapshot_id: str) -> DAGNodeManifest | None:
        """Fetch and reconstruct a DAGNodeManifest by snapshot ID."""
        with self._connect() as con:
            cur = con.execute(
                "SELECT * FROM nodes WHERE snapshot_id = ?", (snapshot_id,)
            )
            node_row = cur.fetchone()
            if node_row is None:
                return None

            pcur = con.execute(
                """
                SELECT parent_id, parent_sha256 FROM node_parents
                WHERE snapshot_id = ? ORDER BY parent_order ASC
                """,
                (snapshot_id,),
            )
            parents = tuple(
                ParentRef(
                    snapshot_id=p["parent_id"], manifest_sha256=p["parent_sha256"]
                )
                for p in pcur.fetchall()
            )

            ptcur = con.execute(
                """
                SELECT relation_name, part_path, row_count, byte_size, sha256, min_value, max_value
                FROM parts WHERE snapshot_id = ? ORDER BY id ASC
                """,
                (snapshot_id,),
            )
            rel_map: dict[str, list[PartDescriptor]] = {}
            for prow in ptcur.fetchall():
                pdesc = PartDescriptor(
                    path=prow["part_path"],
                    sha256=prow["sha256"],
                    row_count=prow["row_count"],
                    byte_size=prow["byte_size"],
                    key_min=prow["min_value"],
                    key_max=prow["max_value"],
                )
                rel_map.setdefault(prow["relation_name"], []).append(pdesc)

            relations = {k: tuple(v) for k, v in rel_map.items()}
            schema_versions = json.loads(node_row["schema_versions_json"] or "{}")
            metadata = json.loads(node_row["metadata_json"] or "{}")

            return DAGNodeManifest(
                snapshot_id=node_row["snapshot_id"],
                kind=node_row["kind"],
                parents=parents,
                checkpoint_anchor_id=node_row["checkpoint_anchor_id"],
                lineage_depth=node_row["lineage_depth"],
                created_at=node_row["created_at"],
                relations=relations,
                logical_fingerprint=node_row["logical_fingerprint"],
                schema_versions=schema_versions,
                metadata=metadata,
            )

    def has_snapshot(self, snapshot_id: str) -> bool:
        """Report whether a snapshot exists in the catalog."""
        with self._connect() as con:
            cur = con.execute(
                "SELECT 1 FROM nodes WHERE snapshot_id = ?", (snapshot_id,)
            )
            return cur.fetchone() is not None

    def get_manifest_sha256(self, snapshot_id: str) -> str | None:
        """Return the manifest sha256 for a given snapshot."""
        with self._connect() as con:
            cur = con.execute(
                "SELECT manifest_sha256 FROM nodes WHERE snapshot_id = ?",
                (snapshot_id,),
            )
            row = cur.fetchone()
            return str(row["manifest_sha256"]) if row else None

    def read_pointer(self, branch_name: str = "main") -> dict[str, Any] | None:
        """Read the tip snapshot pointer for a given branch."""
        with self._connect() as con:
            cur = con.execute(
                """
                SELECT b.snapshot_id, b.updated_at, n.manifest_sha256
                FROM branches b
                LEFT JOIN nodes n ON b.snapshot_id = n.snapshot_id
                WHERE b.name = ?
                """,
                (branch_name,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "snapshot_id": row["snapshot_id"],
                "branch_name": branch_name,
                "updated_at": row["updated_at"],
                "manifest_sha256": row["manifest_sha256"],
            }

    def write_pointer(self, branch_name: str, snapshot_id: str) -> None:
        """Update or create a branch pointer."""
        now_iso = datetime.now(UTC).isoformat()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO branches (name, snapshot_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    snapshot_id = excluded.snapshot_id,
                    updated_at = excluded.updated_at
                """,
                (branch_name, snapshot_id, now_iso),
            )

    def list_branches(self) -> dict[str, str]:
        """Return a mapping of branch name to snapshot ID."""
        with self._connect() as con:
            cur = con.execute("SELECT name, snapshot_id FROM branches ORDER BY name")
            return {row["name"]: row["snapshot_id"] for row in cur.fetchall()}

    def create_tag(self, name: str, snapshot_id: str, message: str = "") -> None:
        """Tag a snapshot with an immutable name and message."""
        now_iso = datetime.now(UTC).isoformat()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO tags (name, snapshot_id, created_at, message)
                VALUES (?, ?, ?, ?)
                """,
                (name, snapshot_id, now_iso, message),
            )

    def get_tag(self, name: str) -> dict[str, Any] | None:
        """Retrieve tag record by name."""
        with self._connect() as con:
            cur = con.execute(
                "SELECT name, snapshot_id, created_at, message FROM tags WHERE name = ?",
                (name,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)

    def list_tags(self) -> list[dict[str, Any]]:
        """List all tags sorted by creation time."""
        with self._connect() as con:
            cur = con.execute(
                "SELECT name, snapshot_id, created_at, message FROM tags ORDER BY created_at"
            )
            return [dict(r) for r in cur.fetchall()]

    def delete_tag(self, name: str) -> bool:
        """Delete a tag by name."""
        with self._connect() as con:
            cur = con.execute("DELETE FROM tags WHERE name = ?", (name,))
            return cur.rowcount > 0

    def walk_lineage(self, tip_id: str) -> list[DAGNodeManifest]:
        """Walk lineage back to checkpoint anchor and return manifests anchor-first."""
        with self._connect() as con:
            cur = con.execute(
                """
                WITH RECURSIVE lineage(snapshot_id, kind, depth) AS (
                    SELECT snapshot_id, kind, 0
                    FROM nodes WHERE snapshot_id = ?
                    UNION ALL
                    SELECT n.snapshot_id, n.kind, l.depth + 1
                    FROM nodes n
                    JOIN node_parents np ON n.snapshot_id = np.parent_id
                    JOIN lineage l ON np.snapshot_id = l.snapshot_id
                    WHERE l.kind != 'checkpoint'
                )
                SELECT snapshot_id, MAX(depth) AS max_depth
                FROM lineage
                GROUP BY snapshot_id
                ORDER BY max_depth DESC;
                """,
                (tip_id,),
            )
            snap_ids = [row["snapshot_id"] for row in cur.fetchall()]

        manifests: list[DAGNodeManifest] = []
        for sid in snap_ids:
            m = self.get_manifest(sid)
            if m is not None:
                manifests.append(m)
        return manifests

    def get_active_parts(
        self, tip_id: str, relation_names: set[str] | None = None
    ) -> list[PartDescriptor]:
        """Retrieve part descriptors active in the lineage of tip_id."""
        with self._connect() as con:
            if relation_names:
                placeholders = ",".join("?" for _ in relation_names)
                sql = f"""
                WITH RECURSIVE lineage(snapshot_id, kind, depth) AS (
                    SELECT snapshot_id, kind, 0
                    FROM nodes WHERE snapshot_id = ?
                    UNION ALL
                    SELECT n.snapshot_id, n.kind, l.depth + 1
                    FROM nodes n
                    JOIN node_parents np ON n.snapshot_id = np.parent_id
                    JOIN lineage l ON np.snapshot_id = l.snapshot_id
                    WHERE l.kind != 'checkpoint'
                ),
                ordered_lineage AS (
                    SELECT snapshot_id, MAX(depth) AS max_depth
                    FROM lineage
                    GROUP BY snapshot_id
                )
                SELECT part_path, row_count, byte_size, sha256, min_value, max_value
                FROM parts p JOIN ordered_lineage l ON p.snapshot_id = l.snapshot_id
                WHERE p.relation_name IN ({placeholders})
                ORDER BY l.max_depth DESC, p.id ASC;
                """
                params = [tip_id, *sorted(relation_names)]
            else:
                sql = """
                WITH RECURSIVE lineage(snapshot_id, kind, depth) AS (
                    SELECT snapshot_id, kind, 0
                    FROM nodes WHERE snapshot_id = ?
                    UNION ALL
                    SELECT n.snapshot_id, n.kind, l.depth + 1
                    FROM nodes n
                    JOIN node_parents np ON n.snapshot_id = np.parent_id
                    JOIN lineage l ON np.snapshot_id = l.snapshot_id
                    WHERE l.kind != 'checkpoint'
                ),
                ordered_lineage AS (
                    SELECT snapshot_id, MAX(depth) AS max_depth
                    FROM lineage
                    GROUP BY snapshot_id
                )
                SELECT part_path, row_count, byte_size, sha256, min_value, max_value
                FROM parts p JOIN ordered_lineage l ON p.snapshot_id = l.snapshot_id
                ORDER BY l.max_depth DESC, p.id ASC;
                """
                params = [tip_id]

            cur = con.execute(sql, params)
            return [
                PartDescriptor(
                    path=row["part_path"],
                    sha256=row["sha256"],
                    row_count=row["row_count"],
                    byte_size=row["byte_size"],
                    key_min=row["min_value"],
                    key_max=row["max_value"],
                )
                for row in cur.fetchall()
            ]

    def resolve_relation(
        self,
        snapshot_id: str,
        relation: str,
        *,
        relative_to: Path | None = None,
        verify_digests: bool = True,
    ) -> tuple[Path, ...]:
        """Resolve a node relation and verify each file against its descriptor."""
        node = self.get_manifest(snapshot_id)
        if node is None:
            raise ValueError(f"snapshot is not in the DAG catalog: {snapshot_id}")
        descriptors = node.relations.get(relation, ())
        if not descriptors:
            raise ValueError(f"snapshot {snapshot_id!r} has no {relation!r} relation")
        root = self.catalog_file.parent.resolve()
        base = Path(relative_to).resolve() if relative_to is not None else root
        if base != root and root not in base.parents:
            raise ValueError("DAG relation base escapes the catalog root")
        paths: list[Path] = []
        for part in descriptors:
            candidate = Path(part.path)
            path = (
                candidate if candidate.is_absolute() else base / candidate
            ).resolve()
            if path != root and root not in path.parents:
                raise ValueError(f"DAG part escapes the catalog root: {part.path}")
            if not path.is_file():
                raise ValueError(f"DAG part is missing: {part.path}")
            if verify_digests and (not part.sha256 or file_sha256(path) != part.sha256):
                raise ValueError(f"DAG part digest mismatch: {part.path}")
            paths.append(path)
        return tuple(paths)

    def prune_parts_for_range(
        self, tip_id: str, relation_name: str, min_key: str, max_key: str
    ) -> list[PartDescriptor]:
        """Prune parts via B-Tree range search across active lineage."""
        with self._connect() as con:
            cur = con.execute(
                """
                WITH RECURSIVE lineage(snapshot_id, kind, depth) AS (
                    SELECT snapshot_id, kind, 0
                    FROM nodes WHERE snapshot_id = ?
                    UNION ALL
                    SELECT n.snapshot_id, n.kind, l.depth + 1
                    FROM nodes n
                    JOIN node_parents np ON n.snapshot_id = np.parent_id
                    JOIN lineage l ON np.snapshot_id = l.snapshot_id
                    WHERE l.kind != 'checkpoint'
                ),
                ordered_lineage AS (
                    SELECT snapshot_id, MAX(depth) AS max_depth
                    FROM lineage
                    GROUP BY snapshot_id
                )
                SELECT part_path, row_count, byte_size, sha256, min_value, max_value
                FROM parts p JOIN ordered_lineage l ON p.snapshot_id = l.snapshot_id
                WHERE p.relation_name = ?
                  AND (p.min_value IS NULL OR p.min_value <= ?)
                  AND (p.max_value IS NULL OR p.max_value >= ?)
                ORDER BY l.max_depth DESC, p.id ASC;
                """,
                (tip_id, relation_name, max_key, min_key),
            )
            return [
                PartDescriptor(
                    path=row["part_path"],
                    sha256=row["sha256"],
                    row_count=row["row_count"],
                    byte_size=row["byte_size"],
                    key_min=row["min_value"],
                    key_max=row["max_value"],
                )
                for row in cur.fetchall()
            ]

    def list_snapshots(self) -> list[dict[str, Any]]:
        """List all snapshots in topological/chronological order."""
        with self._connect() as con:
            cur = con.execute(
                """
                SELECT snapshot_id, kind, parent_id, checkpoint_anchor_id,
                       created_at, lineage_depth, manifest_sha256
                FROM nodes ORDER BY created_at ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]

    def audit_graph(self) -> dict[str, Any]:
        """Audit graph integrity: cycles, missing parents, and foreign keys."""
        with self._connect() as con:
            cur = con.execute("SELECT COUNT(*) AS c FROM nodes")
            node_count = cur.fetchone()["c"]

            cur = con.execute("SELECT COUNT(*) AS c FROM parts")
            part_count = cur.fetchone()["c"]

            # Orphan parent check
            cur = con.execute(
                """
                SELECT n.snapshot_id, n.parent_id
                FROM nodes n
                LEFT JOIN nodes p ON n.parent_id = p.snapshot_id
                WHERE n.parent_id IS NOT NULL AND p.snapshot_id IS NULL;
                """
            )
            orphans = [dict(r) for r in cur.fetchall()]

            # Cycle detection
            cur = con.execute(
                """
                WITH RECURSIVE paths(root, curr, path, is_cycle) AS (
                    SELECT snapshot_id, parent_id, '/' || snapshot_id || '/', 0
                    FROM nodes WHERE parent_id IS NOT NULL
                    UNION ALL
                    SELECT p.root, n.parent_id, p.path || n.snapshot_id || '/',
                           INSTR(p.path, '/' || n.snapshot_id || '/') > 0
                    FROM nodes n JOIN paths p ON n.snapshot_id = p.curr
                    WHERE NOT p.is_cycle AND n.parent_id IS NOT NULL
                )
                SELECT DISTINCT root FROM paths WHERE is_cycle = 1;
                """
            )
            cycles = [r["root"] for r in cur.fetchall()]

            # Distinct physical parts
            cur = con.execute("SELECT DISTINCT part_path FROM parts")
            all_parts = [r["part_path"] for r in cur.fetchall()]

            return {
                "node_count": node_count,
                "part_count": part_count,
                "orphan_nodes": orphans,
                "cycles": cycles,
                "part_paths": all_parts,
            }


__all__ = ["DAGCatalog"]
