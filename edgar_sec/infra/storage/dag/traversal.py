"""Lineage traversal and DAG cycle verification.

Walks from a tip backward through multi-parent ancestors to checkpoint anchors using DAGCatalog.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from .manifest import DAGNodeManifest


class LineageError(RuntimeError):
    """Base error for DAG lineage failures."""


class CycleDetectedError(LineageError):
    """A cycle was detected in the ancestor path."""


class BrokenLineageError(LineageError):
    """An ancestor manifest is missing or unreadable."""


class DigestMismatchError(LineageError):
    """An ancestor manifest hash diverges from the recorded parent digest."""


@dataclass(frozen=True, slots=True)
class LineageChain:
    """Ordered ancestor path from checkpoint anchors to tip in topological order."""

    tip_id: str
    checkpoint_anchor_id: str
    nodes: tuple[DAGNodeManifest, ...]

    @property
    def depth(self) -> int:
        return len(self.nodes) - 1

    def node_for(self, snapshot_id: str) -> DAGNodeManifest | None:
        for node in self.nodes:
            if node.snapshot_id == snapshot_id:
                return node
        return None


def walk_lineage(snapshots_root: Path | str, tip_id: str) -> LineageChain:
    """Traverse DAG from tip backward, returning topological linear order."""
    root = Path(snapshots_root)
    catalog = DAGCatalog(root)

    audit = catalog.audit_graph()
    if audit.get("cycles"):
        raise CycleDetectedError(f"cycle detected involving {audit['cycles']}")

    if not catalog.has_snapshot(tip_id):
        raise BrokenLineageError(f"manifest missing for {tip_id}")

    nodes = catalog.walk_lineage(tip_id)
    if not nodes:
        raise BrokenLineageError(f"lineage empty for {tip_id}")

    for node in nodes:
        if node.kind != "checkpoint":
            if not node.parents:
                raise BrokenLineageError(
                    f"delta node {node.snapshot_id} has no parents"
                )
            for parent_ref in node.parents:
                p_digest = catalog.get_manifest_sha256(parent_ref.snapshot_id)
                if p_digest is None:
                    raise BrokenLineageError(
                        f"parent manifest missing for {parent_ref.snapshot_id}"
                    )
                if (
                    parent_ref.manifest_sha256
                    and p_digest != parent_ref.manifest_sha256
                ):
                    raise DigestMismatchError(
                        f"parent manifest digest mismatch for {parent_ref.snapshot_id}: "
                        f"expected {parent_ref.manifest_sha256}, got {p_digest}"
                    )

    ordered = tuple(nodes)
    primary_anchor = ordered[0].snapshot_id
    return LineageChain(
        tip_id=tip_id,
        checkpoint_anchor_id=primary_anchor,
        nodes=ordered,
    )


@lru_cache(maxsize=128)
def _cached_lineage(root_str: str, tip_id: str) -> LineageChain:
    return walk_lineage(Path(root_str), tip_id)


def resolve_lineage(snapshots_root: Path | str, tip_id: str) -> LineageChain:
    """Return topological lineage chain, using in-memory LRU cache."""
    return _cached_lineage(str(Path(snapshots_root).resolve()), tip_id)


def clear_lineage_cache() -> None:
    """Clear in-memory lineage cache."""
    _cached_lineage.cache_clear()


__all__ = [
    "BrokenLineageError",
    "CycleDetectedError",
    "DigestMismatchError",
    "LineageChain",
    "LineageError",
    "clear_lineage_cache",
    "resolve_lineage",
    "walk_lineage",
]
