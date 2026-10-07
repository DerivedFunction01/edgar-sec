"""Unified command-line interface for the snapshot DAG engine.

Provides inspection, lineage traversal, checkout, diagnostics, and garbage collection.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from collections.abc import Sequence
from typing import Any

from .compaction import compact_lineage
from .doctor import audit_graph
from .manifest import DAGNodeManifest, read_manifest
from .paths import DAGPaths
from .publication import (
    checkout_tip,
    create_branch,
    delete_branch,
    list_branches,
    pointer_path_for,
    publish_node,
    read_pointer,
    read_pointer_id,
)
from .renderer import DAGSwimlaneRenderer, GraphNode, build_graph_nodes
from .retention import analyze_retention, discover_roots, purge_unreferenced
from .spec import RelationSpec
from .tags import create_tag, delete_tag, list_tags, read_tag
from .traversal import walk_lineage


def _emit(data: dict[str, Any] | list[Any]) -> None:
    print(json.dumps(data, indent=2))


def cmd_status(
    snapshots_root: Path,
    *,
    branch_name: str | None = None,
    as_json: bool = False,
) -> int:
    """Report current pointer state, active branch, and lineage metrics."""
    ptr = read_pointer(snapshots_root, branch_name=branch_name)
    if ptr is None:
        target = f"branch '{branch_name}'" if branch_name else "default pointer"
        if as_json:
            _emit({"error": f"no active snapshot pointer for {target}"})
        else:
            print(f"No active snapshot pointer in {snapshots_root} ({target})")
        return 1
    tip_id = str(ptr["snapshot_id"])
    lineage = walk_lineage(snapshots_root, tip_id)
    tip = lineage.nodes[-1]
    tags = [
        t["tag"] for t in list_tags(snapshots_root) if t.get("snapshot_id") == tip_id
    ]
    info = {
        "snapshots_root": str(snapshots_root),
        "branch": branch_name or "current",
        "tip_snapshot_id": tip_id,
        "kind": tip.kind,
        "checkpoint_anchor_id": tip.checkpoint_anchor_id,
        "lineage_depth": lineage.depth,
        "ancestor_count": len(lineage.nodes),
        "relations": {k: len(v) for k, v in tip.relations.items()},
        "tags": tags,
        "created_at": tip.created_at,
    }
    if as_json:
        _emit(info)
    else:
        print(f"Branch: {branch_name or 'current'} -> Tip: {tip_id} ({tip.kind})")
        print(f"Anchor: {tip.checkpoint_anchor_id} | Depth: {lineage.depth}")
        if tags:
            print(f"Tags: {', '.join(tags)}")
        print(
            f"Relations: {', '.join(f'{k}:{len(v)}' for k, v in tip.relations.items())}"
        )
    return 0


def cmd_log(
    snapshots_root: Path,
    *,
    branch_name: str | None = None,
    limit: int | None = None,
    graph: bool = False,
    all_heads: bool = False,
    as_json: bool = False,
) -> int:
    """List topological node lineage from root to tip or render swimlanes."""
    if graph:
        return _render_graph_log(
            snapshots_root,
            branch_name=branch_name,
            all_heads=all_heads,
            limit=limit,
            as_json=as_json,
        )

    ptr = read_pointer(snapshots_root, branch_name=branch_name)
    if ptr is None:
        return 1
    lineage = walk_lineage(snapshots_root, str(ptr["snapshot_id"]))
    nodes = list(reversed(lineage.nodes))
    if limit is not None:
        nodes = nodes[:limit]
    records = [
        {
            "snapshot_id": n.snapshot_id,
            "kind": n.kind,
            "parents": [p.snapshot_id for p in n.parents],
            "checkpoint_anchor_id": n.checkpoint_anchor_id,
            "depth": n.lineage_depth,
            "created_at": n.created_at,
        }
        for n in nodes
    ]
    if as_json:
        _emit(records)
    else:
        for r in records:
            parents = ",".join(r["parents"]) or "none"
            anchor = (
                f" (anchor: {r['checkpoint_anchor_id']})"
                if r["checkpoint_anchor_id"]
                and r["checkpoint_anchor_id"] not in r["parents"]
                else ""
            )
            print(f"* [{r['kind']}] {r['snapshot_id']} (parents: {parents}){anchor}")
    return 0


def _render_graph_log(
    snapshots_root: Path,
    *,
    branch_name: str | None,
    all_heads: bool,
    limit: int | None,
    as_json: bool,
) -> int:
    """Render DAG topology via cycle-tolerant swimlane renderer."""
    graph_nodes = build_graph_nodes(
        snapshots_root, branch_name=branch_name, all_heads=all_heads
    )
    renderer = DAGSwimlaneRenderer(graph_nodes)
    if as_json:
        order, cycles = renderer.compute_order()
        _emit({"order": order, "cycles": cycles})
    else:
        print(renderer.render(limit=limit))
    return 0


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
    pointer_file = pointer_path_for(root, branch_name)
    current_id = read_pointer_id(pointer_file)

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
    *,
    expected_parent_id: str | None = None,
    branch_name: str | None = None,
    allow_null: bool = False,
    as_json: bool = False,
) -> int:
    """Publish a staged snapshot node and atomically advance pointer."""
    manifest_path = DAGPaths(staged_dir).staged_manifest_file(staged_dir)
    if not manifest_path.is_file():
        if as_json:
            _emit({"error": f"staged manifest not found: {manifest_path}"})
        else:
            print(f"Error: staged manifest not found: {manifest_path}")
        return 1

    manifest = read_manifest(manifest_path)
    pointer_file = pointer_path_for(snapshots_root, branch_name=branch_name)
    current_id = read_pointer_id(pointer_file)

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


def cmd_doctor(
    snapshots_root: Path,
    *,
    verify_digests: bool = True,
    as_json: bool = False,
) -> int:
    """Run diagnostics on lineage and repository integrity."""
    audit = audit_graph(snapshots_root, verify_digests=verify_digests)
    report = {
        "snapshots_root": str(snapshots_root),
        "healthy": audit.is_healthy,
        "error_count": len(audit.errors),
        "warning_count": len(audit.warnings),
        "errors": list(audit.errors),
        "warnings": list(audit.warnings),
        "active_tips": list(audit.active_tips),
    }
    if as_json:
        _emit(report)
    else:
        status = "HEALTHY" if audit.is_healthy else f"ISSUES ({len(audit.errors)})"
        print(f"Repository {snapshots_root}: {status}")
        for err in audit.errors:
            print(f"  ERROR: {err}")
        for warn in audit.warnings:
            print(f"  WARN: {warn}")
    return 0 if audit.is_healthy else 1


def _resolve_specs(
    target: str | None,
    tip_manifest: DAGNodeManifest | None = None,
) -> Sequence[RelationSpec]:
    """Dynamically resolve relation specs for compaction."""
    import importlib

    if target:
        if target in ("inventory", "document_inventory"):
            mod = importlib.import_module(
                "edgar_sec.pipelines.document_inventory.snapshot.specs"
            )
            return getattr(mod, "INVENTORY_RELATIONS")
        if target in ("metadata", "metadata_sync"):
            mod = importlib.import_module("edgar_sec.pipelines.metadata_sync.specs")
            return getattr(mod, "METADATA_RELATIONS")
        if ":" in target:
            mod_name, attr_name = target.split(":", 1)
            mod = importlib.import_module(mod_name)
            return getattr(mod, attr_name)
        raise ValueError(f"unknown relation specs target: {target}")

    if tip_manifest is not None:
        rel_names = set(tip_manifest.relations.keys())
        if "accessions" in rel_names or "entries" in rel_names:
            mod = importlib.import_module(
                "edgar_sec.pipelines.document_inventory.snapshot.specs"
            )
            return getattr(mod, "INVENTORY_RELATIONS")
        if "submissions" in rel_names:
            mod = importlib.import_module("edgar_sec.pipelines.metadata_sync.specs")
            return getattr(mod, "METADATA_RELATIONS")

    raise ValueError("cannot resolve relation specs; specify --specs")


def cmd_compact(
    snapshots_root: Path,
    *,
    branch_name: str | None = None,
    specs_target: str | None = None,
    new_snapshot_id: str | None = None,
    publish: bool = True,
    as_json: bool = False,
) -> int:
    """Compact active lineage into a standalone Checkpoint snapshot."""
    ptr = read_pointer(snapshots_root, branch_name=branch_name)
    if ptr is None:
        if as_json:
            _emit({"error": "no active snapshot pointer"})
        else:
            print(f"No active snapshot pointer in {snapshots_root}")
        return 1
    tip_id = str(ptr["snapshot_id"])
    lineage = walk_lineage(snapshots_root, tip_id)
    tip = lineage.nodes[-1]

    try:
        specs = _resolve_specs(specs_target, tip)
    except Exception as exc:
        if as_json:
            _emit({"error": str(exc)})
        else:
            print(f"Failed to resolve relation specs: {exc}")
        return 1

    target_id = new_snapshot_id or f"{tip_id}_compacted"
    staged = DAGPaths(snapshots_root).staging_dir(target_id)
    try:
        manifest = compact_lineage(
            snapshots_root,
            specs,
            tip_id=tip_id,
            new_snapshot_id=target_id,
            staged_dir=staged,
            publish=publish,
            branch_name=branch_name,
        )
    finally:
        if staged.exists():
            shutil.rmtree(staged, ignore_errors=True)

    info = {
        "snapshot_id": manifest.snapshot_id,
        "kind": manifest.kind,
        "tip_id": tip_id,
        "checkpoint_anchor_id": manifest.checkpoint_anchor_id,
        "lineage_depth": manifest.lineage_depth,
        "logical_fingerprint": manifest.logical_fingerprint,
        "relations": {k: len(v) for k, v in manifest.relations.items()},
        "published": publish,
    }
    if as_json:
        _emit(info)
    else:
        print(f"Compacted {tip_id} -> {manifest.snapshot_id} (published={publish})")
        print(f"Logical fingerprint: {manifest.logical_fingerprint}")
    return 0


def cmd_gc(
    snapshots_root: Path,
    *,
    dry_run: bool = False,
    as_json: bool = False,
) -> int:
    """Collect unreferenced snapshot nodes and orphan parts."""
    report = analyze_retention(snapshots_root)
    purged = purge_unreferenced(snapshots_root, report, dry_run=dry_run)
    payload = {
        "prunable_snapshots": list(report.prunable_snapshots),
        "purged_snapshots": purged,
        "reclaimed_bytes": report.prunable_byte_size,
        "dry_run": dry_run,
    }
    if as_json:
        _emit(payload)
    else:
        print(f"Reclaimed {report.prunable_byte_size} bytes")
        print(f"Purged snapshots: {len(purged)}")
    return 0


def configure_dag_subcommands(
    sub: argparse._SubParsersAction,
    *,
    default_root: Path | Callable[[], Path] | None = None,
    default_specs: Sequence[RelationSpec]
    | Callable[[], Sequence[RelationSpec]]
    | None = None,
) -> None:
    """Configure common DAG subcommands on a subparser action."""
    status_p = sub.add_parser("status", help="Show current snapshot status")
    status_p.add_argument("--branch", default=None, help="Target branch name")

    log_p = sub.add_parser("log", help="Display lineage history")
    log_p.add_argument("-n", "--limit", type=int, default=None, help="Max entries")
    log_p.add_argument("--branch", default=None, help="Target branch name")
    log_p.add_argument("--graph", action="store_true", help="Render ASCII swimlanes")
    log_p.add_argument(
        "--all", action="store_true", help="Include all branch and tag heads"
    )

    pub_p = sub.add_parser("publish", help="Publish a staged snapshot node")
    pub_p.add_argument("staged_dir", type=Path, help="Staged directory to publish")
    pub_p.add_argument(
        "--expected-parent", default=None, help="Expected parent snapshot ID"
    )
    pub_p.add_argument(
        "--allow-null", action="store_true", help="Allow publishing genesis node"
    )
    pub_p.add_argument("--branch", default=None, help="Branch name to publish to")

    br_p = sub.add_parser("branch", help="List, create, or delete branches")
    br_p.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "create", "delete"],
        help="Branch action",
    )
    br_p.add_argument("name", nargs="?", default=None, help="Branch name")
    br_p.add_argument("--from", dest="from_id", default=None, help="Source snapshot ID")

    tag_p = sub.add_parser("tag", help="List, create, or delete tags")
    tag_p.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "create", "delete"],
        help="Tag action",
    )
    tag_p.add_argument("name", nargs="?", default=None, help="Tag name")
    tag_p.add_argument("target", nargs="?", default=None, help="Target snapshot ID")
    tag_p.add_argument("-m", "--message", default="", help="Tag message annotation")

    co_p = sub.add_parser("checkout", help="Switch current or branch pointer")
    co_p.add_argument("target", help="Target snapshot ID, branch, or tag")
    co_p.add_argument("--branch", default=None, help="Target branch to switch")
    co_p.add_argument(
        "--force", action="store_true", help="Override lineage affinity guard"
    )

    doc_p = sub.add_parser("doctor", help="Run integrity checks")
    doc_p.add_argument(
        "--skip-digests", action="store_true", help="Skip SHA-256 digest checks"
    )

    cmp_p = sub.add_parser("compact", help="Consolidate lineage into a checkpoint")
    cmp_p.add_argument("--branch", default=None, help="Branch to compact")
    cmp_p.add_argument("--specs", default=None, help="Relation specs specifier")
    cmp_p.add_argument("--new-id", default=None, help="New checkpoint snapshot ID")
    cmp_p.add_argument(
        "--no-publish", action="store_true", help="Do not advance current pointer"
    )

    gc_p = sub.add_parser("gc", help="Collect unreferenced snapshots and parts")
    gc_p.add_argument("--dry-run", action="store_true", help="Preview deletions")


def attach_dag_subparser(
    subparsers: argparse._SubParsersAction,
    *,
    subcommand_name: str = "dag",
    help_text: str = "Snapshot DAG operations",
    default_root: Path | Callable[[], Path] | None = None,
    default_specs: Sequence[RelationSpec]
    | Callable[[], Sequence[RelationSpec]]
    | None = None,
) -> argparse.ArgumentParser:
    """Attach DAG subparser tree with pre-bound defaults for pipeline CLIs."""
    dag_parser = subparsers.add_parser(subcommand_name, help=help_text)
    dag_parser.add_argument(
        "--root", type=Path, default=None, help="Snapshots directory"
    )
    dag_parser.add_argument("--json", action="store_true", help="Format output as JSON")
    sub = dag_parser.add_subparsers(dest="subcommand", required=True)
    configure_dag_subcommands(
        sub, default_root=default_root, default_specs=default_specs
    )
    return dag_parser


def dispatch_dag_subcommand(
    args: argparse.Namespace,
    *,
    default_root: Path | Callable[[], Path] | None = None,
    default_specs: Sequence[RelationSpec]
    | Callable[[], Sequence[RelationSpec]]
    | None = None,
) -> int:
    """Execute parsed DAG subcommand options against resolved root."""
    if getattr(args, "root", None) is not None:
        root = args.root.resolve()
    elif callable(default_root):
        root = default_root().resolve()
    elif default_root is not None:
        root = Path(default_root).resolve()
    else:
        root = Path(".").resolve()

    as_json = bool(getattr(args, "json", False))
    sub = getattr(args, "subcommand", None)

    if sub == "status":
        return cmd_status(root, branch_name=args.branch, as_json=as_json)
    if sub == "log":
        return cmd_log(
            root,
            branch_name=args.branch,
            limit=args.limit,
            graph=args.graph,
            all_heads=args.all,
            as_json=as_json,
        )
    if sub == "publish":
        return cmd_publish(
            root,
            args.staged_dir.resolve(),
            expected_parent_id=args.expected_parent,
            branch_name=args.branch,
            allow_null=args.allow_null,
            as_json=as_json,
        )
    if sub == "branch":
        return cmd_branch(
            root,
            action=args.action,
            name=args.name,
            from_snapshot_id=args.from_id,
            as_json=as_json,
        )
    if sub == "tag":
        return cmd_tag(
            root,
            action=args.action,
            name=args.name,
            target=args.target,
            message=args.message,
            as_json=as_json,
        )
    if sub == "checkout":
        return cmd_checkout(
            root, args.target, branch_name=args.branch, force=args.force
        )
    if sub == "doctor":
        return cmd_doctor(root, verify_digests=not args.skip_digests, as_json=as_json)
    if sub == "compact":
        specs_target = args.specs
        if specs_target is None and default_specs is not None:
            specs = default_specs() if callable(default_specs) else default_specs
            specs_target = None
        return cmd_compact(
            root,
            branch_name=args.branch,
            specs_target=specs_target,
            new_snapshot_id=args.new_id,
            publish=not args.no_publish,
            as_json=as_json,
        )
    if sub == "gc":
        return cmd_gc(root, dry_run=args.dry_run, as_json=as_json)
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for DAG operations."""
    parser = argparse.ArgumentParser(prog="dag", description="Snapshot DAG CLI")
    parser.add_argument(
        "--root", type=Path, default=Path("."), help="Snapshots directory"
    )
    parser.add_argument("--json", action="store_true", help="Format output as JSON")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    configure_dag_subcommands(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for DAG CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return dispatch_dag_subcommand(args)


__all__ = [
    "attach_dag_subparser",
    "build_parser",
    "cmd_branch",
    "cmd_checkout",
    "cmd_compact",
    "cmd_doctor",
    "cmd_gc",
    "cmd_log",
    "cmd_publish",
    "cmd_status",
    "cmd_tag",
    "configure_dag_subcommands",
    "dispatch_dag_subcommand",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
