"""DAG operator reference commands: branches and tags."""

from __future__ import annotations

from pathlib import Path

from ..tags import create_tag, delete_tag, list_tags
from ..working.publication import (
    create_branch,
    delete_branch,
    list_branches,
    read_pointer,
)
from .output import _emit


def cmd_branch(
    snapshots_root: Path,
    action: str = "list",
    name: str | None = None,
    *,
    from_snapshot_id: str | None = None,
    as_json: bool = False,
) -> int:
    """List, create, or delete branches."""
    if action == "list":
        branches = list_branches(snapshots_root)
        records = []
        for b in branches:
            ptr = read_pointer(
                snapshots_root, branch_name=None if b == "current" else b
            )
            s_id = str(ptr["snapshot_id"]) if ptr else "none"
            records.append(
                {"branch": b, "snapshot_id": s_id, "is_current": b == "current"}
            )
        if as_json:
            _emit(records)
        else:
            for r in records:
                prefix = "* " if r["is_current"] else "  "
                print(f"{prefix}{r['branch']:<16} -> {r['snapshot_id']}")
        return 0

    if action == "create":
        if not name:
            print("Error: branch name required for create")
            return 1
        target_id = from_snapshot_id
        if target_id is None:
            curr_ptr = read_pointer(snapshots_root)
            if curr_ptr is None:
                print("Error: no current snapshot to branch from; specify --from")
                return 1
            target_id = str(curr_ptr["snapshot_id"])
        create_branch(snapshots_root, name, target_id)
        if as_json:
            _emit({"status": "created", "branch": name, "snapshot_id": target_id})
        else:
            print(f"Created branch '{name}' pointing to {target_id}")
        return 0

    if action == "delete":
        if not name:
            print("Error: branch name required for delete")
            return 1
        deleted = delete_branch(snapshots_root, name)
        if not deleted:
            print(f"Error: branch '{name}' not found")
            return 1
        if as_json:
            _emit({"status": "deleted", "branch": name})
        else:
            print(f"Deleted branch '{name}'")
        return 0

    return 1


def cmd_tag(
    snapshots_root: Path,
    action: str = "list",
    name: str | None = None,
    target: str | None = None,
    *,
    message: str = "",
    as_json: bool = False,
) -> int:
    """List, create, or delete immutable tags."""
    if action == "list":
        tags = list_tags(snapshots_root)
        if as_json:
            _emit(tags)
        else:
            for t in tags:
                msg = f" [{t['message']}]" if t.get("message") else ""
                print(
                    f"{t['tag']:<16} -> {t['snapshot_id']} ({t['created_at'][:10]}){msg}"
                )
        return 0

    if action == "create":
        if not name or not target:
            print("Error: tag name and target snapshot ID required for create")
            return 1
        tag_path = create_tag(snapshots_root, name, target, message=message)
        if as_json:
            _emit(
                {
                    "status": "created",
                    "tag": name,
                    "snapshot_id": target,
                    "path": str(tag_path),
                }
            )
        else:
            print(f"Created tag '{name}' -> {target}")
        return 0

    if action == "delete":
        if not name:
            print("Error: tag name required for delete")
            return 1
        deleted = delete_tag(snapshots_root, name)
        if not deleted:
            print(f"Error: tag '{name}' not found")
            return 1
        if as_json:
            _emit({"status": "deleted", "tag": name})
        else:
            print(f"Deleted tag '{name}'")
        return 0

    return 1


__all__ = [
    "cmd_branch",
    "cmd_tag",
]
