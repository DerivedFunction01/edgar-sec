"""The interactive augmentation journey.

Augmentation is the one action whose *cohort* is a question rather than a file.
The curated CSV this pipeline plans over is a seed: it is a list someone curated
at a point in time, and it goes stale as registrants appear. Re-augmenting that
same seed after it has been fully ingested asks for nothing new, and asking for
everything the seed names would refetch what the base already holds. So the
question the operator actually needs answered is "which registrants exist now
that this base snapshot does not have", and the honest way to answer it is the
union of the seed with the active listings in a published SEC source snapshot.

This module owns that journey: discover or refresh the source observation, build
the cohort, choose the base, and show the resulting arithmetic. It is separate
from ``operator`` because no other menu action needs a source snapshot, a base
snapshot, or a preflight; keeping them together made one file carry two unrelated
surfaces.

It imports ``WizardState`` and ``confirm_network`` from ``operator``, which
imports :func:`run_augment` inside the action body rather than at module scope.
The indirection is what lets a phase-local flow reuse the session's own state and
consent policy without either module owning the other.
"""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.interactive import prompt_text
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings

from .augmentation import preflight_augment
from .cli import cmd_augment, cmd_refresh
from .discovery import (
    SourceSummary,
    current_snapshot_id,
    describe_roster,
    describe_source,
    list_input_manifests,
    list_rosters,
    list_snapshots,
    list_source_snapshots,
    resolve_snapshot_choice,
    resolve_source_choice,
)
from .merger import MergeError
from .operator import DEFAULT_INPUT, WizardState, confirm_network
from .options import PlanOptions, plan_options, resolve_cohort
from .registry import ensure_registry

__all__ = [
    "ask_augment_cohort",
    "ask_base_snapshot",
    "readable_sources",
    "run_augment",
]


def run_augment(state: WizardState) -> None:
    """Add the CIKs a chosen cohort has and the base snapshot lacks.

    The order of the questions is the design. Cohort, then base, then the
    arithmetic, and only then consent to spend SEC request budget. The boring
    outcome -- the base already covers the request -- is decided from published
    artifacts alone, so it costs no network request, no published delta plan, and
    no pointer change, and it reports as a result rather than a traceback.
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

    Only published snapshots are offered. An unpublished finalized artifact is
    not a snapshot, and treating one as a base would publish a delta over data no
    reader can resolve to. The current pointer is the default because
    augment-forward is the common case, but earlier snapshots stay reachable:
    backfilling onto an older base is a legitimate correction.
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


def ask_augment_cohort(state: WizardState) -> PlanOptions | None:
    """Choose which CIKs this augmentation should consider requested.

    Source-aware comparison leads, because a two-year-old seed plus today's
    listings is the cohort that actually reflects the registrants who exist. A
    published comparison, a discovered CIK manifest, and a hand-typed path remain
    available, and every one of them is treated as a *request* whose real work is
    decided by subtraction against the base -- including a file that already
    looks like a delta.
    """
    metadata = state.metadata()
    seed = prompt_text("Curated seed CSV", DEFAULT_INPUT).strip()
    if not seed:
        return None
    if not Path(seed).is_file():
        print(f"{seed} does not exist")
        return None

    sources = readable_sources(list_source_snapshots(metadata))
    if not sources and not _offer_source_refresh(state):
        return None
    if not sources:
        sources = readable_sources(list_source_snapshots(metadata))
    if not sources:
        return None

    rosters = [item for item in list_rosters(metadata) if item["readable"]]
    inputs = [item for item in list_input_manifests() if item["readable"]]

    print("\nCohort to request:")
    print(f"  1. {seed} + {describe_source(sources[0])}  (seed and active listings)")
    for index, roster in enumerate(rosters, start=2):
        print(f"  {index}. {describe_roster(roster)}")
    offset = 2 + len(rosters)
    for index, item in enumerate(inputs, start=offset):
        print(f"  {index}. {item['name']}  ({item['row_count']:,} CIKs)")
    custom = offset + len(inputs)
    print(f"  {custom}. Another path...")
    answer = prompt_text("Cohort number", "1").strip() or "1"
    try:
        choice = int(answer)
    except ValueError:
        choice = 1

    if choice == 1:
        registry_id = _resolve_source_roster(state, seed, sources)
        if not registry_id:
            return None
        return plan_options(registry_id=registry_id)
    if 2 <= choice < offset:
        return plan_options(registry_id=str(rosters[choice - 2]["registry_id"]))
    if offset <= choice < custom:
        return plan_options(
            input_path=Path(str(inputs[choice - offset]["input_path"])).resolve()
        )
    if choice == custom:
        typed = prompt_text("CIK manifest CSV", "").strip()
        if not typed:
            return None
        if not Path(typed).is_file():
            print(f"{typed} does not exist")
            return None
        return plan_options(input_path=Path(typed).resolve())
    print("invalid selection")
    return None


def readable_sources(sources: list[SourceSummary]) -> list[SourceSummary]:
    """Source snapshots a comparison can actually be run against."""
    return [item for item in sources if item["readable"]]


def _refresh_source(state: WizardState) -> None:
    """Publish a source snapshot into the artifacts root this session is using.

    Passing ``None`` here would resolve the *project* default, which is a
    different tree from the one the session is reading snapshots and plans from.
    An operator who scoped the session to another artifacts root would get their
    source snapshot written outside it, and the comparison would then fail to
    find it.
    """
    cmd_refresh(Path(state.artifacts_root) if state.artifacts_root else None)


def _offer_source_refresh(state: WizardState) -> bool:
    """Offer to publish a source snapshot when none is on disk yet.

    Defaults to no, for the reason every other fetch in this operator does: it is a
    live SEC request, and publishing an immutable snapshot nobody asked for is a side
    effect that outlives the session.
    """
    print("\nNo SEC listing source snapshot on disk; cohorts cannot be compared.")
    if not confirm_network("Fetch the live SEC company ticker listing now? (y/N) "):
        print("cancelled; nothing was fetched")
        return False
    _refresh_source(state)
    return True


def _resolve_source_roster(
    state: WizardState, seed: str, sources: list[SourceSummary]
) -> str:
    """Resolve the effective roster for a seed and a source snapshot.

    The comparison is a pure projection of two immutable files, so it runs on
    demand without network access and is reused whenever the same pair has already
    been compared.
    """
    source_id = ""
    if len(sources) > 1:

        def select(lines: list[str]) -> str:
            print("\nSEC listing source snapshots (newest first):")
            for line in lines:
                print(line)
            if confirm_network("Fetch a fresh SEC listing first? (y/N) "):
                _refresh_source(state)
                refreshed = readable_sources(list_source_snapshots(state.metadata()))
                if refreshed:
                    sources[:] = refreshed
            return "1"

        source_id = resolve_source_choice(sources, select=select)
        if not source_id:
            print("cancelled; no source snapshot selected")
            return ""
    else:
        source_id = str(sources[0]["snapshot_id"])
    try:
        result = ensure_registry(
            curated_input_path=seed,
            source_snapshot_id=source_id,
            metadata_paths=state.metadata(),
        )
    except (OSError, ValueError, MergeError) as exc:
        print(f"could not build the seed/source cohort: {exc}")
        return ""
    print(
        f"  seed and active listings: {result['row_count']:,} CIKs (source {source_id})"
    )
    return str(result["registry_id"])
