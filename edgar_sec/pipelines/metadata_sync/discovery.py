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
from pathlib import Path
from typing import Any

from edgar_sec.infra.storage.manifests import list_snapshots as _scan_snapshot_manifests

from .paths import (
    REGISTRIES_DIR_NAME,
    SNAPSHOT_MANIFEST_NAME,
    MetadataPaths,
    resolve_run_paths,
)
from .registry import RegistryError
from .roster import RosterError
from .source_registry import SOURCE_MANIFEST_KIND, SOURCE_NAME

__all__ = [
    "InputSummary",
    "PlanSummary",
    "RosterSummary",
    "SourceSummary",
    "current_snapshot_id",
    "describe_roster",
    "describe_source",
    "list_input_manifests",
    "list_plans",
    "list_rosters",
    "list_snapshots",
    "list_source_snapshots",
    "plan_summary",
    "resolve_input_choice",
    "resolve_plan_choice",
    "resolve_snapshot_choice",
    "resolve_source_choice",
]


class PlanSummary(dict[str, Any]):
    """One discovered plan, as plain data the operator renders and picks from."""


class RosterSummary(dict[str, Any]):
    """One discovered effective-CIK roster, as plain pickable data."""


class SourceSummary(dict[str, Any]):
    """One published external source snapshot, as plain pickable data."""


class InputSummary(dict[str, Any]):
    """One candidate CIK manifest CSV, as plain pickable data."""


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


def list_rosters(metadata: MetadataPaths) -> list[RosterSummary]:
    """Every published effective-CIK roster a plan can be built from.

    A roster is what ``sources compare`` publishes, and it is a content address
    over one source snapshot plus one curated input. Listing them is what lets a
    plan be created from a discovered cohort instead of a hand-typed roster id the
    operator was never shown.

    A registry whose roster dataset or its manifest is missing, or whose digest no
    longer matches what was published, is reported as unreadable rather than
    dropped: the operator is told a registry exists and that it cannot currently
    be planned from, which is different from never having run ``compare``.
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
            # The manifest is provenance, not the plan's input: the roster digest
            # above already decided whether this registry is usable. A missing or
            # foreign manifest leaves the counts unknown, which is reported as
            # such rather than as a registry that cannot be planned from.
            manifest = {}
        summary["source_snapshot_id"] = str(manifest.get("source_snapshot_id", ""))
        summary["curated_cik_count"] = int(manifest.get("curated_cik_count", 0) or 0)
        summary["active_cik_count"] = int(manifest.get("active_cik_count", 0) or 0)
        found.append(summary)
    return found


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


def describe_roster(roster: RosterSummary) -> str:
    """One-line human summary of a roster's provenance and size."""
    if not roster["readable"]:
        return f"{roster['registry_id']}  unusable ({roster['readable_reason']})"
    parts = [f"{roster['row_count']:,} CIKs"]
    if roster["active_cik_count"]:
        parts.append(f"{roster['active_cik_count']:,} active in source")
    parts.append(f"source {roster['source_snapshot_id'] or 'unknown'}")
    return f"{roster['registry_id']}  " + ", ".join(parts)


def list_source_snapshots(metadata: MetadataPaths) -> list[SourceSummary]:
    """Every published external source snapshot, newest retrieval first.

    The curated CSV this pipeline plans over is a *seed*: it is a file someone
    curated at a point in time, and it goes stale as registrants are added.
    Augmentation exists to close that gap, which means the operator has to be
    able to see which SEC listing observations are already on disk and how old
    they are before choosing a cohort. Ordering by ``retrieved_at`` is what makes
    "the latest" mean something.

    Only manifests are read, matching every other listing here. A snapshot whose
    manifest is unreadable is reported as such rather than dropped, so an
    operator is told a source exists and that it cannot currently be read.
    """
    root = metadata.sources_root / SOURCE_NAME
    if not root.is_dir():
        return []
    found: list[SourceSummary] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        path = metadata.source_manifest_file(SOURCE_NAME, entry.name)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            found.append(
                SourceSummary(
                    snapshot_id=entry.name,
                    manifest_path=str(path),
                    retrieved_at="",
                    unique_cik_count=0,
                    listing_row_count=0,
                    readable=False,
                    readable_reason=str(exc),
                )
            )
            continue
        if not isinstance(manifest, dict):
            manifest = {}
        readable = manifest.get("manifest_kind") == SOURCE_MANIFEST_KIND
        found.append(
            SourceSummary(
                snapshot_id=str(manifest.get("snapshot_id", "") or entry.name),
                manifest_path=str(path),
                retrieved_at=str(manifest.get("retrieved_at", "")),
                unique_cik_count=int(manifest.get("unique_cik_count", 0) or 0),
                listing_row_count=int(manifest.get("listing_row_count", 0) or 0),
                readable=readable,
                readable_reason="" if readable else "not a source manifest",
            )
        )
    found.sort(
        key=lambda item: (item["retrieved_at"], item["snapshot_id"]), reverse=True
    )
    return found


def describe_source(source: SourceSummary) -> str:
    """One-line human summary of a source snapshot's age and coverage."""
    if not source["readable"]:
        return f"{source['snapshot_id']}  unreadable ({source['readable_reason']})"
    parts = [f"retrieved {source['retrieved_at'] or 'unknown'}"]
    if source["unique_cik_count"]:
        parts.append(f"{source['unique_cik_count']:,} CIKs")
    if source["listing_row_count"]:
        parts.append(f"{source['listing_row_count']:,} listings")
    return f"{source['snapshot_id']}  " + ", ".join(parts)


def resolve_source_choice(
    sources: list[SourceSummary], *, select: Callable[[list[str]], str]
) -> str:
    """Choose one source snapshot id from discovered snapshots.

    Returns the empty string when the operator cancels, which the caller reads
    as "do not proceed". A lone snapshot is still offered rather than adopted:
    which observations a cohort is built from is a decision, and the whole point
    of restoring this listing is that the answer is visible before it is made.
    """
    if not sources:
        return ""
    lines = [
        f"  {index}. {describe_source(source)}"
        for index, source in enumerate(sources, start=1)
    ]
    choice = select(lines)
    if not choice:
        return ""
    try:
        index = int(choice)
    except ValueError:
        return ""
    if not 1 <= index <= len(sources):
        return ""
    return str(sources[index - 1]["snapshot_id"])


def list_input_manifests(directory: str | Path | None = None) -> list[InputSummary]:
    """Candidate CIK manifest CSVs, by path.

    The curated seed and any hand-supplied delta list both live here, and neither
    is distinguishable by name: a file called ``cik-sec.csv`` may be the original
    universe or an increment over it. Guessing from the filename is how an
    operator ends up silently augmenting against the wrong idea of what they
    asked for, so a candidate is reported as a CIK manifest and nothing more. The
    authoritative question -- which of its CIKs the base snapshot is missing -- is
    answered by subtraction against the chosen base, not here.

    Each candidate is parsed once so an unreadable or empty file is reported as
    unusable rather than offered and then failing mid-run. The row count is shown
    because it is the only thing that distinguishes a two-year-old seed from a
    hand-built increment.
    """
    from edgar_sec.foundation.runtime.paths import resolve_paths

    root = Path(directory) if directory is not None else resolve_paths().uploads_root
    if not root.is_dir():
        return []
    from .manifest import read_cik_manifest

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
            manifest = read_cik_manifest(path)
        except (OSError, ValueError) as exc:
            summary["readable_reason"] = str(exc)
        else:
            summary["row_count"] = len(manifest.ciks)
            summary["readable"] = True
        found.append(summary)
    found.sort(key=lambda item: item["name"])
    return found


def resolve_input_choice(
    inputs: list[InputSummary], *, select: Callable[[list[str]], str]
) -> str:
    """Choose one CIK manifest path from discovered candidates.

    Returns the empty string when the operator cancels or types an answer that
    names no candidate, which leaves a hand-typed path available: the listing
    exists to save remembering, not to forbid typing.
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

    Returns the empty string when the operator keeps the current pointer or
    cancels, which the caller reads as "leave the pointer alone". A lone snapshot
    is still offered rather than adopted: switching which dataset a reader
    resolves to is a decision, not an inference, even when there is only one
    candidate to decide about.
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


def _describe(plan: PlanSummary) -> str:
    """One-line human summary of a plan's size, progress, and kind.

    The kind and parent are shown because a delta plan is a plan the ordinary
    run/merge path cannot publish on its own: merging one would publish the delta
    alone and drop the base rows it names as its parent. Rendering both kinds
    identically gave an operator no way to tell which one they were looking at.
    """
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
