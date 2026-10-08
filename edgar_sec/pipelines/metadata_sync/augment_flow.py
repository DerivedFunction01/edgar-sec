"""Interactive selection and execution for snapshot augmentation."""

from __future__ import annotations

from edgar_sec.foundation.runtime.interactive import (
    PickItem,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths

from .augmentation import preflight_augment
from .cli import cmd_augment
from .discovery import (
    current_snapshot_id,
    list_snapshots,
    resolve_snapshot_choice,
)
from .merger import MergeError
from .operator import WizardState, confirm_network
from .options import PlanOptions, plan_options, resolve_cohort

__all__ = [
    "ask_augment_cohort",
    "ask_base_snapshot",
    "ask_published_cohort",
    "run_augment",
]


def run_augment(state: WizardState) -> None:
    """Add the CIKs a chosen cohort has and the base snapshot lacks.
    The already-covered outcome is decided from published artifacts, so it costs
    no request, no delta plan, and no pointer change.
    """
    metadata = state.metadata()
    options = ask_augment_cohort(state)
    if options is None:
        return

    base = ask_base_snapshot(metadata)
    if not base:
        print("cancelled; an augment needs a base snapshot")
        return

    try:
        check = preflight_augment(
            resolve_cohort(options).roster, metadata, base_snapshot_id=base
        )
    except (OSError, ValueError, MergeError) as exc:
        print(f"cannot plan that augmentation: {exc}")
        return
    print(f"\n{check.describe()}")
    if check.is_empty:
        print(
            f"Base {base} already holds every requested CIK. Nothing was fetched,"
            " no delta plan was written, and the current snapshot is unchanged."
        )
        return

    options.chunk_size = _ask_chunk_size(resolve_runtime_settings().default_chunk_size)
    if not confirm_network(
        f"Fetching {check.delta_count:,} CIKs from SEC. Continue? (y/N) "
    ):
        print("cancelled; nothing was fetched")
        return
    cmd_augment(
        options,
        base_snapshot_id=base,
        new_snapshot_id=prompt_text(
            "New snapshot id (blank = the derived delta plan id)", ""
        ).strip(),
        workers=_ask_workers(),
    )
    published = current_snapshot_id(metadata)
    if published:
        print(f"current snapshot is now {published}")


def _ask_chunk_size(default: int) -> int:
    answer = prompt_text(
        "CIKs per chunk (blank = configured default)", str(default)
    ).strip()
    if not answer:
        return default
    try:
        return int(answer)
    except ValueError:
        print(f"'{answer}' is not a whole number; using the configured default")
        return default


def _ask_workers() -> int | None:
    answer = prompt_text("Worker threads (blank = machine-derived)", "").strip()
    if not answer:
        return None
    try:
        return int(answer)
    except ValueError:
        print(f"'{answer}' is not a whole number; using the machine-derived default")
        return None


def ask_base_snapshot(metadata) -> str:
    """Choose the published snapshot this augmentation builds on.
    Only published snapshots are offered: an unpublished artifact is not a snapshot.
    """
    manifests = list_snapshots(metadata)
    if not manifests:
        print("no published snapshot to augment; merge a plan first")
        return ""
    current = current_snapshot_id(metadata)
    if current:
        print(f"\nCurrent snapshot: {current}")
    if len(manifests) == 1:
        return str(manifests[0].get("snapshot_id", ""))

    def select(lines: list[str]) -> str:
        print("\nBase snapshots:")
        for line in lines:
            print(line)
        return prompt_text("Base snapshot number (blank = current)", "").strip()

    chosen = resolve_snapshot_choice(manifests, current, select=select)
    return chosen or current


def ask_published_cohort(state: WizardState, *, purpose: str) -> PlanOptions | None:
    """Pick a published cohort through the shared catalog picker."""
    paths = resolve_cohort_paths(state.metadata().artifacts_root)
    catalog = CohortCatalog(paths)
    offset = 0
    records = []
    while True:
        page = catalog.list_cohorts(limit=100, offset=offset)
        records.extend(page)
        if len(page) < 100:
            break
        offset += len(page)
    items = [
        PickItem(
            key=record.cohort_id,
            label=(f"{record.name or record.cohort_id}  ({record.row_count:,} CIKs)"),
            value=record,
        )
        for record in records
    ]
    if not items:
        print("no published cohorts are available")
        return None
    selected = prompt_paginated_choice(items, prompt_label=purpose)
    if selected is None:
        return None
    return plan_options(
        cohort=selected.value.cohort_id,
        artifacts_root=state.artifacts_root or None,
    )


def ask_augment_cohort(state: WizardState) -> PlanOptions | None:
    """Choose the published cohort to request against the base snapshot."""
    return ask_published_cohort(state, purpose="Cohort to augment")
