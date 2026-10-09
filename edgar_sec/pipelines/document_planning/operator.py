"""Interactive operator for document-target planning."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from edgar_sec.domain.plan.discovery import discover_plans
from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    PickItem,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_choice,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_planning.discovery import (
    discover_document_plans,
)
from edgar_sec.pipelines.document_planning.catalog_scope import resolve_catalog_scope
from edgar_sec.pipelines.document_planning.commands.inspect import cmd_inspect
from edgar_sec.pipelines.document_planning.commands.status import cmd_status
from edgar_sec.pipelines.document_planning.paths import (
    DocumentPlanningPaths,
    resolve_catalog_paths,
    resolve_document_planning_paths,
    resolve_inventory_paths,
)
from edgar_sec.pipelines.document_planning.planner import (
    DocumentPlanningError,
    create_document_plan,
    coverage_preflight,
    resolve_inventory_snapshot_id,
)
from edgar_sec.pipelines.document_planning.profiles import (
    compatible_with_catalog_only,
    discover_profiles,
)
from .cli import main as cli_main

MENU_TITLE = "Document Planning"


@dataclass(slots=True)
class OperatorSession:
    evidence_mode: str | None = None
    catalog_plan_id: str | None = None
    profile_id: str | None = None
    snapshot_id: str | None = None
    plan_id: str | None = None

    def header(self) -> str:
        return (
            "Last selections: "
            f"mode={self.evidence_mode or 'unset'}, "
            f"catalog={self.catalog_plan_id or 'unset'}, "
            f"snapshot={self.snapshot_id or 'unset'}, "
            f"profile={self.profile_id or 'unset'}, "
            f"plan={self.plan_id or 'unset'}"
        )


def _catalog_plans(paths: DocumentPlanningPaths) -> list[dict[str, Any]]:
    catalog_paths = resolve_catalog_paths(paths.artifacts_root)
    return [item.raw for item in discover_plans(catalog_paths.plans_root)]


def _catalog_choice(
    paths: DocumentPlanningPaths, default: str | None = None
) -> str | None:
    discovered = _catalog_plans(paths)
    items: list[PickItem] = []
    for manifest in discovered:
        plan_id = str(manifest.get("plan_id") or "")
        try:
            scope = resolve_catalog_scope(
                plan_id, resolve_catalog_paths(paths.artifacts_root)
            )
            unique_accessions = sum(1 for _ in scope.iter_accessions())
            locator_rows = sum(part.rows for part in scope.parts)
        except (ValueError, OSError) as error:
            print(f"skipping unusable catalog plan {plan_id}: {error}")
            continue
        label = (
            f"{plan_id}  {unique_accessions:,} distinct accessions, "
            f"{locator_rows:,} locator rows"
        )
        items.append(PickItem(plan_id, label, plan_id))
    chosen = prompt_paginated_choice(
        items, prompt_label="Select published catalog plan", default=default
    )
    return str(chosen.value) if chosen is not None else None


def _profile_choice(
    paths: DocumentPlanningPaths,
    *,
    catalog_only: bool,
    default: str | None = None,
) -> str | None:
    choices: list[PickItem] = []
    for item in discover_profiles(paths.profiles_root):
        if item.profile is None:
            print(f"invalid profile {item.profile_id}: {item.error}")
            continue
        if catalog_only and not compatible_with_catalog_only(item.profile):
            continue
        profile = item.profile
        choices.append(
            PickItem(
                profile.profile_id,
                f"{profile.profile_id} v{profile.version} ({profile.digest[:12]})",
                profile.profile_id,
            )
        )
    chosen = prompt_paginated_choice(
        choices, prompt_label="Select target profile", default=default
    )
    return str(chosen.value) if chosen is not None else None


def _snapshot_choices(paths: DocumentPlanningPaths) -> list[PickItem]:
    inventory_paths = resolve_inventory_paths(paths.artifacts_root)
    catalog = DAGCatalog(inventory_paths.snapshots_root, read_only=True)
    snapshots = catalog.list_snapshots()
    pointer = catalog.read_pointer("main")
    current_id = str(pointer["snapshot_id"]) if pointer else None
    items: list[PickItem] = []
    for snapshot in reversed(snapshots):
        snapshot_id = str(snapshot["snapshot_id"])
        node = catalog.get_manifest(snapshot_id)
        accessions = sum(
            part.row_count for part in node.relations.get("accessions", ())
        )
        label = f"{snapshot_id}  {accessions:,} indexed accessions"
        if snapshot_id == current_id:
            label += " [current]"
        items.append(PickItem(snapshot_id, label, snapshot_id))
    if current_id and current_id not in {item.key for item in items}:
        items.insert(0, PickItem(current_id, f"{current_id} [current]", current_id))
    return items


def _snapshot_choice(
    paths: DocumentPlanningPaths, default: str | None = None
) -> str | None:
    items = _snapshot_choices(paths)
    selected_default = default or next(
        (item.key for item in items if "[current]" in item.label), None
    )
    chosen = prompt_paginated_choice(
        items,
        prompt_label="Select immutable inventory snapshot",
        default=selected_default,
    )
    return str(chosen.value) if chosen is not None else None


def _action_plan(session: OperatorSession) -> None:
    paths = resolve_document_planning_paths()
    mode = prompt_choice(
        "Select evidence mode",
        [
            ("1", "Catalog metadata only (primary requests only)"),
            ("2", "Catalog plus pinned inventory snapshot"),
            ("0", "Cancel"),
        ],
        default=session.evidence_mode or "0",
    )
    if mode == "0":
        return
    session.evidence_mode = mode
    catalog_plan_id = _catalog_choice(paths, session.catalog_plan_id)
    if catalog_plan_id is None:
        return
    session.catalog_plan_id = catalog_plan_id
    catalog_only = mode == "1"
    profile_id = _profile_choice(
        paths, catalog_only=catalog_only, default=session.profile_id
    )
    if profile_id is None:
        return
    session.profile_id = profile_id
    snapshot_id = None
    if not catalog_only:
        selected = _snapshot_choice(paths, session.snapshot_id)
        if selected is None:
            return
        try:
            snapshot_id = resolve_inventory_snapshot_id(selected, paths)
            preflight = coverage_preflight(catalog_plan_id, snapshot_id or "", paths)
        except (DocumentPlanningError, ValueError, OSError) as error:
            print(f"coverage preflight failed: {error}")
            return
        print(f"resolved inventory snapshot: {preflight.snapshot_id}")
        print(
            "read-only coverage: "
            f"{preflight.indexed_accessions:,} indexed / "
            f"{preflight.unindexed_accessions:,} unindexed of "
            f"{preflight.scoped_accessions:,} catalog accessions"
        )
        if preflight.unindexed_accessions:
            print(
                "project the selected accessions with 'inventory project' before planning"
            )
        session.snapshot_id = preflight.snapshot_id
    confirmation = prompt_text("Publish this immutable target plan? [y/N]", "n")
    if confirmation.strip().casefold() not in {"y", "yes"}:
        print("plan publication cancelled")
        return
    try:
        result = create_document_plan(
            catalog_plan_id,
            profile_id,
            snapshot_id,
            paths,
        )
    except (DocumentPlanningError, ValueError, OSError) as error:
        print(f"planning refused: {error}")
        return
    print(f"published document plan {result.plan_id}")
    print(
        f"  source pins {result.manifest['catalog_plan_digest']} / "
        f"{result.manifest['inventory_snapshot_digest']}"
    )
    print(f"  coverage {result.manifest['distinct_accession_coverage']}")
    print(f"  statuses {result.manifest['status_counts']}")
    session.plan_id = result.plan_id


def _action_inspect(session: OperatorSession) -> None:
    paths = resolve_document_planning_paths()
    items = [
        PickItem(item.plan_id, item.plan_id, item.plan_id)
        for item in discover_document_plans(paths)
        if item.plan is not None
    ]
    selected = prompt_paginated_choice(
        items,
        prompt_label="Select published target plan",
        default=session.plan_id,
    )
    if selected is None:
        return
    cmd_inspect(
        argparse.Namespace(plan_id=str(selected.value), artifacts="", json=False)
    )


def _action_status() -> None:
    import argparse

    cmd_status(argparse.Namespace(artifacts="", json=False))


def build_operator_menu(
    session: OperatorSession | None = None,
) -> tuple[MenuAction, ...]:
    state = session or OperatorSession()
    return build_menu(
        menu_action("Plan document targets", lambda: _action_plan(state)),
        menu_action("Inspect a published plan", lambda: _action_inspect(state)),
        menu_action("List plans and profiles", _action_status),
    )


def main(argv: list[str] | None = None) -> int:
    session = OperatorSession()
    return operator_entrypoint(
        MENU_TITLE,
        build_operator_menu(session),
        cli_main,
        argv,
        before_menu=session.header,
    )


if __name__ == "__main__":
    sys.exit(main())
