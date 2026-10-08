"""What is already on disk, for the interactive operator to choose from.

Only manifests are read, never a Parquet payload, so a listing stays cheap
enough to run on every menu render.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from .paths import (
    PLANS_DIR_NAME,
    REGISTRIES_DIR_NAME,
    SNAPSHOT_MANIFEST_NAME,
    MetadataPaths,
    resolve_run_paths,
)
from .registry import RegistryError
from .roster import RosterError

__all__ = [
    "InputSummary",
    "PlanSummary",
    "RosterSummary",
    "current_snapshot_id",
    "describe_plan",
    "describe_roster",
    "list_input_manifests",
    "list_plans",
    "list_rosters",
    "list_snapshots",
    "plan_summary",
    "resolve_input_choice",
    "resolve_plan_choice",
    "resolve_snapshot_choice",
]


class PlanSummary(dict[str, Any]):
    """One discovered plan, as plain data the operator renders and picks from."""


class RosterSummary(dict[str, Any]):
    """One discovered effective-CIK roster, as plain pickable data."""


class InputSummary(dict[str, Any]):
    """One candidate CIK manifest CSV, as plain pickable data."""


def _read_plan_manifest(metadata: MetadataPaths, plan_id: str) -> dict[str, Any]:
    """Read one plan's manifest without validating or loading its cohort.
    Validation is skipped so a plan this build cannot use can still be listed.
    """
    path = metadata.plan_dir(plan_id) / PLAN_FILE_NAME
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
    ``created_at`` is second-resolution and ties; directory mtime does not, and
    ``plan_id`` breaks what remains.
    """
    root = metadata.metadata_root / PLANS_DIR_NAME
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
    """Every published metadata snapshot manifest."""
    catalog = DAGCatalog(metadata.snapshots_root)
    if not catalog.catalog_file.is_file():
        return []
    return catalog.list_snapshots()


def list_rosters(metadata: MetadataPaths) -> list[RosterSummary]:
    """Every published effective-CIK roster a plan can be built from.
    An unreadable registry is reported, not dropped.
    """
    root = metadata.metadata_root / REGISTRIES_DIR_NAME
    if not root.is_dir():
        return []
    from .registry import load_registry_manifest, load_registry_roster

    found: list[RosterSummary] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        # Key assignment, not attribute assignment: these summaries are dicts, and
        # a plain attribute would leave the key every reader looks up empty.
        summary = RosterSummary(
            {
                "registry_id": entry.name,
                "row_count": 0,
                "readable": False,
                "readable_reason": "",
                "source_snapshot_id": "",
                "curated_cik_count": 0,
                "active_cik_count": 0,
            }
        )
        try:
            roster = load_registry_roster(entry.name, metadata)
        except (OSError, ValueError, RosterError) as exc:
            summary["readable_reason"] = str(exc)
        else:
            summary["row_count"] = roster.row_count
            summary["readable"] = True
        try:
            manifest = load_registry_manifest(entry.name, metadata)
        except (OSError, ValueError, KeyError, RegistryError):
            # The manifest is provenance, not the plan's input; the roster
            # digest already decided usability, so missing counts stay unknown.
            manifest = {}
        summary["source_snapshot_id"] = str(manifest.get("source_snapshot_id", ""))
        summary["curated_cik_count"] = int(manifest.get("curated_cik_count", 0) or 0)
        summary["active_cik_count"] = int(manifest.get("active_cik_count", 0) or 0)
        found.append(summary)
    return found


def current_snapshot_id(metadata: MetadataPaths) -> str:
    """Snapshot id named by the catalog pointer, or empty when unset."""
    catalog = DAGCatalog(metadata.snapshots_root)
    ptr = catalog.read_pointer()
    return str(ptr["snapshot_id"]) if ptr else ""


def resolve_plan_choice(
    plans: list[PlanSummary], *, select: Callable[[list[str]], str]
) -> PlanSummary | None:
    """Choose one plan from a discovered list using a supplied picker.
    Injected rather than called, so this module stays free of terminal I/O.
    """
    if not plans:
        return None
    if len(plans) == 1:
        return plans[0]
    lines = []
    for index, plan in enumerate(plans, start=1):
        state = describe_plan(plan)
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


def describe_roster(roster: RosterSummary) -> str:
    """One-line human summary of a roster's provenance and size."""
    if not roster["readable"]:
        return f"{roster['registry_id']}  unusable ({roster['readable_reason']})"
    parts = [f"{roster['row_count']:,} CIKs"]
    if roster["active_cik_count"]:
        parts.append(f"{roster['active_cik_count']:,} active in source")
    parts.append(f"source {roster['source_snapshot_id'] or 'unknown'}")
    return f"{roster['registry_id']}  " + ", ".join(parts)


def list_input_manifests(directory: str | Path | None = None) -> list[InputSummary]:
    """Candidate CIK manifest CSVs, by path.
    The seed and a hand-supplied delta are indistinguishable by name, so a
    candidate is reported as a CIK manifest and nothing more.
    """
    from edgar_sec.foundation.runtime.paths import resolve_paths

    root = Path(directory) if directory is not None else resolve_paths().uploads_root
    if not root.is_dir():
        return []
    from .manifest import count_cohort_rows

    found: list[InputSummary] = []
    for path in sorted(root.glob("*.csv")):
        summary = InputSummary(
            input_path=str(path),
            name=path.name,
            row_count=0,
            readable=False,
            readable_reason="",
        )
        try:
            # Counted, not compiled: a menu render must not write an
            # artifact nobody asked for.
            rows = count_cohort_rows(path)
        except (OSError, ValueError) as exc:
            summary["readable_reason"] = str(exc)
        else:
            if rows == 0:
                summary["readable_reason"] = (
                    f"input manifest contains no usable CIKs: {path}"
                )
            else:
                summary["row_count"] = rows
                summary["readable"] = True
        found.append(summary)
    found.sort(key=lambda item: item["name"])
    return found


def resolve_input_choice(
    inputs: list[InputSummary], *, select: Callable[[list[str]], str]
) -> str:
    """Choose one CIK manifest path from discovered candidates.
    Empty on cancel, which leaves a hand-typed path available.
    """
    if not inputs:
        return ""
    lines = [
        f"  {index}. {item['name']}  ({item['row_count']:,} CIKs)"
        if item["readable"]
        else f"  {index}. {item['name']}  unreadable ({item['readable_reason']})"
        for index, item in enumerate(inputs, start=1)
    ]
    choice = select(lines)
    if not choice:
        return ""
    try:
        index = int(choice)
    except ValueError:
        return ""
    if not 1 <= index <= len(inputs):
        return ""
    chosen = inputs[index - 1]
    return str(chosen["input_path"]) if chosen["readable"] else ""


def resolve_snapshot_choice(
    manifests: list[dict[str, Any]],
    current_id: str,
    *,
    select: Callable[[list[str]], str],
) -> str:
    """Choose one published snapshot id from discovered manifests.
    Empty leaves the ``current`` pointer alone.
    """
    if not manifests:
        return ""
    lines = []
    for index, manifest in enumerate(manifests, start=1):
        lines.append(f"  {index}. {_describe_snapshot(manifest, current_id)}")
    choice = select(lines)
    if not choice:
        return ""
    try:
        index = int(choice)
    except ValueError:
        return ""
    if not 1 <= index <= len(manifests):
        return ""
    return str(manifests[index - 1].get("snapshot_id", ""))


def _describe_snapshot(manifest: dict[str, Any], current_id: str) -> str:
    """One-line human summary of a published snapshot."""
    snapshot_id = str(manifest.get("snapshot_id", "?"))
    marker = " [current]" if snapshot_id == current_id else ""
    parts = [f"{int(manifest.get('row_count', 0) or 0):,} rows"]
    if manifest.get("parts"):
        parts.append(f"{len(manifest['parts'])} parts")
    parent = str(manifest.get("parent_snapshot_id", "") or "")
    if parent:
        parts.append(f"augments {parent}")
    if str(manifest.get("kind", "")) == "delta":
        parts.append("delta")
    return f"{snapshot_id}{marker}  " + ", ".join(parts)


def describe_plan(plan: PlanSummary) -> str:
    """One-line human summary of a plan's size, progress, and kind."""
    parts = [f"{plan['row_count']:,} CIKs", f"{plan['chunk_count']} chunks"]
    completed = plan["completed_chunks"]
    if completed < 0:
        parts.append("progress unknown (plan unreadable)")
    else:
        parts.append(f"{completed}/{plan['chunk_count']} done")
    if plan["kind"] == "delta":
        parent = plan["parent_snapshot_id"]
        parts.append(f"delta on {parent}" if parent else "delta (no parent recorded)")
    if plan["published"]:
        parts.append("published")
    return ", ".join(parts)
