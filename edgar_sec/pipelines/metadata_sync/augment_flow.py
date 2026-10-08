"""The interactive augmentation journey.
Augmentation is the one action whose cohort is a question rather than a file: the
honest answer is the union of the curated seed with a published source snapshot.
Imports ``WizardState`` from ``operator``, which imports ``run_augment`` in the body.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.interactive import prompt_text
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
from .operator import DEFAULT_INPUT, WizardState, confirm_network
from .options import PlanOptions, plan_options, resolve_cohort

__all__ = [
    "ask_augment_cohort",
    "ask_base_snapshot",
    "ask_cohort_source",
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
    state.input_path = str(options.input_path or "")
    state.registry_id = options.registry_id

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


def _ask_csv_cohort(
    default: str, *, artifacts_root: Path | None = None
) -> PlanOptions | None:
    """Point at a curated CIK manifest CSV that exists."""
    typed = prompt_text("CIK manifest CSV", default).strip()
    if not typed:
        return None
    if not Path(typed).is_file():
        print(f"{typed} does not exist")
        return None
    return plan_options(input_path=Path(typed).resolve(), artifacts_root=artifacts_root)


def ask_cohort_source(state: WizardState, *, purpose: str) -> PlanOptions | None:
    """Pick a shared published cohort page or retain a curated/registry input."""
    paths = resolve_cohort_paths(state.metadata().artifacts_root)
    catalog = CohortCatalog(paths)
    page_size = 20
    offset = 0
    while True:
        records = catalog.list_cohorts(limit=page_size, offset=offset)
        print(f"\n{purpose} (published cohorts):")
        for index, record in enumerate(records, start=1):
            name = record.name or record.cohort_id
            print(f"  {index}. {name}  ({record.cohort_id}, {record.row_count:,} CIKs)")
        csv_choice = len(records) + 1
        roster_choice = len(records) + 2
        print(f"  {csv_choice}. Curated CSV path...")
        print(f"  {roster_choice}. Published registry roster id...")
        controls = []
        if offset:
            controls.append("p=previous")
        if len(records) == page_size:
            controls.append("n=next")
        suffix = f" ({', '.join(controls)})" if controls else ""
        answer = prompt_text(f"Cohort choice{suffix} (blank=cancel)", "").strip()
        if answer.casefold() == "n" and len(records) == page_size:
            offset += page_size
            continue
        if answer.casefold() == "p" and offset:
            offset = max(0, offset - page_size)
            continue
        if not answer:
            return None
        try:
            choice = int(answer)
        except ValueError:
            print("invalid selection")
            continue
        if 1 <= choice <= len(records):
            return plan_options(
                cohort=records[choice - 1].cohort_id,
                artifacts_root=state.artifacts_root or None,
            )
        if choice == csv_choice:
            return _ask_csv_cohort(
                DEFAULT_INPUT, artifacts_root=state.artifacts_root or None
            )
        if choice == roster_choice:
            registry_id = prompt_text("Published registry roster id", "").strip()
            return (
                plan_options(
                    registry_id=registry_id,
                    artifacts_root=state.artifacts_root or None,
                )
                if registry_id
                else None
            )
        print("invalid selection")


def ask_augment_cohort(state: WizardState) -> PlanOptions | None:
    """Choose which CIKs this augmentation should consider requested.
    Every source is a *request* whose real work is decided by subtraction
    against the base.
    """
    return ask_cohort_source(state, purpose="Cohort to request")
