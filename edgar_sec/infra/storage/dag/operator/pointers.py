"""DAG operator pointer commands: checkout and publish."""

from __future__ import annotations

from pathlib import Path

from ..manifest import DAGNodeManifest
from ..tags import read_tag
from ..working.publication import checkout_tip, publish_node, read_pointer
from ..working.traversal import walk_lineage
from .output import _emit


def cmd_checkout(
    snapshots_root: Path,
    target: str,
    *,
    branch_name: str | None = None,
    force: bool = False,
) -> int:
    """Atomically swing pointer to a target snapshot, branch, or tag."""
    tag_data = read_tag(snapshots_root, target)
    if tag_data:
        target_id = str(tag_data["snapshot_id"])
    else:
        target_id = target

    root = Path(snapshots_root)
    ptr = read_pointer(root, branch_name=branch_name)
    current_id = str(ptr["snapshot_id"]) if ptr else None

    if current_id is not None and not force:
        try:
            _assert_lineage_affinity(root, current_id, target_id)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1

    checkout_tip(snapshots_root, target_id, branch_name=branch_name)
    branch_label = f" (branch '{branch_name}')" if branch_name else ""
    print(f"Checked out tip{branch_label}: {target_id}")
    return 0


def _assert_lineage_affinity(root: Path, current_id: str, target_id: str) -> None:
    """Verify target is an ancestor or descendant of the current tip."""
    try:
        current_lineage = walk_lineage(root, current_id)
    except Exception:
        return
    current_ancestors = {n.snapshot_id for n in current_lineage.nodes}

    if target_id in current_ancestors:
        return

    try:
        target_lineage = walk_lineage(root, target_id)
    except Exception:
        return
    target_ancestors = {n.snapshot_id for n in target_lineage.nodes}

    if current_id in target_ancestors:
        return

    raise ValueError(
        f"checkout blocked: {target_id!r} is not an ancestor or descendant "
        f"of current tip {current_id!r}; use --force to override"
    )


def cmd_publish(
    snapshots_root: Path,
    staged_dir: Path,
    manifest: DAGNodeManifest,
    *,
    expected_parent_id: str | None = None,
    branch_name: str | None = None,
    allow_null: bool = False,
    as_json: bool = False,
) -> int:
    """Publish a staged snapshot node and atomically advance pointer."""
    ptr = read_pointer(snapshots_root, branch_name=branch_name)
    current_id = str(ptr["snapshot_id"]) if ptr else None

    if allow_null:
        if current_id is not None:
            msg = f"pointer already exists ({current_id}); cannot publish genesis with --allow-null"
            if as_json:
                _emit({"error": msg})
            else:
                print(f"Error: {msg}")
            return 1
        expected_parent = None
    else:
        expected_parent = (
            expected_parent_id if expected_parent_id is not None else current_id
        )

    try:
        published_dir = publish_node(
            snapshots_root,
            manifest,
            staged_dir,
            expected_parent,
            branch_name=branch_name,
        )
    except Exception as exc:
        if as_json:
            _emit({"error": str(exc)})
        else:
            print(f"Publication failed: {exc}")
        return 1

    payload = {
        "status": "published",
        "snapshot_id": manifest.snapshot_id,
        "kind": manifest.kind,
        "branch": branch_name or "current",
        "path": str(published_dir),
    }
    if as_json:
        _emit(payload)
    else:
        print(
            f"Published {manifest.kind} '{manifest.snapshot_id}' to branch '{branch_name or 'current'}'"
        )
    return 0


__all__ = [
    "cmd_checkout",
    "cmd_publish",
]
