"""What is already on disk, for the interactive operator to choose from.

v1's wizard discovered its own state: it looked for in-progress runs, listed
published snapshots, marked the current one, and offered a numbered pick. v2's
operator re-prompted for everything and a blank answer did nothing, which made
the pipeline feel like a hand-typed CLI rather than a surface that knows what
already exists.

This module is that discovery, and it is phase-local on purpose.
``roadmap/refactor_v2/v2_refactor_roadmap.md`` records why v1's equivalent was
deliberately not shared: the shared ``run_interactive`` "hardcoded Phase 01's
exact model ... [and] became dead code outside Phase 01", and the v2 remedy was
per-pipeline command surfaces. What is genuinely shared -- the directory scan and
warn-and-skip manifest parse -- is reused from ``infra.storage.manifests`` with
this pipeline's manifest filename passed in.

Every function here reads manifests only. None opens a Parquet payload, so
listing stays cheap enough to run on every menu render.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from edgar_sec.infra.storage.manifests import list_snapshots as _scan_snapshot_manifests

from .paths import SNAPSHOT_MANIFEST_NAME, MetadataPaths, resolve_run_paths

__all__ = [
    "PlanSummary",
    "current_snapshot_id",
    "list_plans",
    "list_snapshots",
    "plan_summary",
    "resolve_plan_choice",
]


class PlanSummary(dict[str, Any]):
    """One discovered plan, as plain data the operator renders and picks from."""


def _read_plan_manifest(metadata: MetadataPaths, plan_id: str) -> dict[str, Any]:
    """Read one plan's manifest without validating or loading its cohort.

    Validation is deliberately skipped: discovery must be able to *list* a plan
    this build cannot use, so the operator can be told why, rather than failing
    on a directory it is trying to report.
    """
    path = metadata.plan_dir(plan_id) / "plan.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def plan_summary(metadata: MetadataPaths, plan_id: str) -> PlanSummary:
    """Summarize one plan: its size, its progress, and whether it was published."""
    manifest = _read_plan_manifest(metadata, plan_id)
    chunk_count = int(manifest.get("chunk_count", 0))
    completed = -1 if not manifest else 0
    if chunk_count and manifest:
        run_paths = resolve_run_paths(plan_id, metadata.artifacts_root)
        try:
            from .checkpoints import discover_completed_chunks
            from .planner import load_plan

            plan = load_plan(run_paths)
            completed = len(discover_completed_chunks(plan, run_paths))
        except (FileNotFoundError, ValueError, OSError):
            # An unreadable, stale, or version-incompatible plan still lists. Its
            # progress is reported as unknown rather than guessed at.
            completed = -1
    return PlanSummary(
        plan_id=plan_id,
        row_count=int(manifest.get("row_count", 0)),
        chunk_size=int(manifest.get("chunk_size", 0)),
        chunk_count=chunk_count,
        completed_chunks=completed,
        created_at=str(manifest.get("created_at", "")),
        kind=str(manifest.get("kind", "")),
        parent_snapshot_id=str(manifest.get("parent_snapshot_id", "")),
        published=metadata.snapshot_manifest(plan_id).is_file(),
        readable=bool(manifest),
    )


def list_plans(metadata: MetadataPaths) -> list[PlanSummary]:
    """Every plan on disk, most recently touched first.

    Newest first because the plan an operator most likely wants is the one they
    just made; v1 auto-resumed the most recent in-progress run on the same
    assumption.

    The key is the plan directory's modification time, not ``created_at``:
    ``created_at`` is recorded to the second, so several plans made in one
    session tie and "newest" would degrade to an arbitrary directory order.
    Modification time also tracks a plan that has been added to since, which is
    the more useful reading. ``plan_id`` breaks remaining ties so the listing is
    deterministic rather than filesystem-order dependent.
    """
    root = metadata.metadata_root / "plans"
    if not root.is_dir():
        return []
    found = [
        plan_summary(metadata, entry.name) for entry in root.iterdir() if entry.is_dir()
    ]
    mtimes = {
        entry.name: entry.stat().st_mtime for entry in root.iterdir() if entry.is_dir()
    }
    return sorted(
        found,
        key=lambda item: (mtimes.get(item["plan_id"], 0.0), item["plan_id"]),
        reverse=True,
    )


def list_snapshots(metadata: MetadataPaths) -> list[dict[str, Any]]:
    """Every published metadata snapshot manifest, reusing the shared scan."""
    return _scan_snapshot_manifests(metadata.snapshots_root, SNAPSHOT_MANIFEST_NAME)


def current_snapshot_id(metadata: MetadataPaths) -> str:
    """Snapshot id named by the ``current`` pointer, or empty when unset."""
    pointer = metadata.current_pointer
    if not pointer.is_file():
        return ""
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("snapshot_id", "")) if isinstance(payload, dict) else ""


def resolve_plan_choice(
    plans: list[PlanSummary], *, select: Callable[[list[str]], str]
) -> PlanSummary | None:
    """Choose one plan from a discovered list using a supplied picker.

    ``select`` receives the rendered choices and returns a plan id, or an empty
    string to cancel. Taking the picker as an argument is what keeps this module
    free of terminal I/O: it decides *what* can be chosen, and the operator
    decides how to ask. The tests supply a scripted picker, and a future
    non-interactive caller can supply its own.
    """
    if not plans:
        return None
    if len(plans) == 1:
        return plans[0]
    lines = []
    for index, plan in enumerate(plans, start=1):
        state = _describe(plan)
        marker = " [current]" if plan["published"] else ""
        lines.append(f"  {index}. {plan['plan_id']}{marker} {state}")
    choice = select(lines)
    if not choice:
        return None
    try:
        index = int(choice)
    except ValueError:
        return None
    if not 1 <= index <= len(plans):
        return None
    return plans[index - 1]


def _describe(plan: PlanSummary) -> str:
    """One-line human summary of a plan's size and progress."""
    parts = [f"{plan['row_count']:,} CIKs", f"{plan['chunk_count']} chunks"]
    completed = plan["completed_chunks"]
    if completed < 0:
        parts.append("progress unknown (plan unreadable)")
    else:
        parts.append(f"{completed}/{plan['chunk_count']} done")
    if plan["published"]:
        parts.append("published")
    return ", ".join(parts)
