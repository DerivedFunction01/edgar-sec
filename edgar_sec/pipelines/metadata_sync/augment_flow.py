"""The interactive augmentation journey.
Augmentation is the one action whose cohort is a question rather than a file: the
honest answer is the union of the curated seed with a published source snapshot.
Imports ``WizardState`` from ``operator``, which imports ``run_augment`` in the body.
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
    list_rosters,
    list_snapshots,
    list_source_snapshots,
    list_universe_snapshots,
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
    "ask_cohort_source",
    "readable_sources",
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


def _ask_csv_cohort(default: str) -> PlanOptions | None:
    """Point at a curated CIK manifest CSV that exists."""
    typed = prompt_text("CIK manifest CSV", default).strip()
    if not typed:
        return None
    if not Path(typed).is_file():
        print(f"{typed} does not exist")
        return None
    return plan_options(input_path=Path(typed).resolve())


def _ask_registry_cohort(state: WizardState) -> PlanOptions | None:
    """Derive a registry cohort by projecting a curated seed against a source.

    This is the only cohort that needs a published source snapshot, so it is
    the only one that asks for one — and it asks after the choice is made.
    """
    seed = _ask_csv_cohort(DEFAULT_INPUT)
    if seed is None or seed.input_path is None:
        return None
    sources = readable_sources(list_source_snapshots(state.metadata()))
    if not sources and not _offer_source_refresh(state):
        return None
    if not sources:
        sources = readable_sources(list_source_snapshots(state.metadata()))
    if not sources:
        return None
    registry_id = _resolve_source_roster(state, str(seed.input_path), sources)
    if not registry_id:
        return None
    return plan_options(registry_id=registry_id)


def ask_cohort_source(state: WizardState, *, purpose: str) -> PlanOptions | None:
    """Choose the cohort a plan or augmentation is built over.

    One picker serves both flows, so a choice meaningful for planning is
    meaningful for augmenting; an entry is listed only when it can be built.
    """
    metadata = state.metadata()
    sources = readable_sources(list_source_snapshots(metadata))
    choices: list[tuple[str, str, str]] = [
        (f"{DEFAULT_INPUT}  (curated manifest CSV)", "csv", ""),
    ]
    for roster in [item for item in list_rosters(metadata) if item["readable"]]:
        choices.append((describe_roster(roster), "roster", str(roster["registry_id"])))
    if sources:
        registry_label = f"{DEFAULT_INPUT} + {describe_source(sources[0])}  (derive a registry cohort)"
    else:
        registry_label = (
            f"{DEFAULT_INPUT} + active listings  (derive a registry cohort; "
            "no source snapshot published yet)"
        )
    choices.append((registry_label, "registry", ""))
    for snapshot in [
        item for item in list_universe_snapshots(metadata) if item["readable"]
    ]:
        choices.append(
            (
                f"full registrant universe  {snapshot['unique_cik_count']:,} CIKs  "
                f"(source {snapshot['snapshot_id']}, retrieved "
                f"{snapshot['retrieved_at'] or 'unknown'})",
                "universe",
                "",
            )
        )
    choices.append(("Another path...", "custom", ""))

    print(f"\n{purpose}:")
    for index, (label, _kind, _payload) in enumerate(choices, start=1):
        print(f"  {index}. {label}")
    answer = prompt_text("Cohort number", "1").strip() or "1"
    try:
        choice = int(answer)
    except ValueError:
        choice = 1
    if not 1 <= choice <= len(choices):
        print("invalid selection")
        return None

    _label, kind, payload = choices[choice - 1]
    if kind == "roster":
        return plan_options(registry_id=payload)
    if kind == "registry":
        return _ask_registry_cohort(state)
    if kind == "universe":
        return plan_options(universe=True, artifacts_root=state.artifacts_root or None)
    return _ask_csv_cohort(DEFAULT_INPUT if kind == "csv" else "")


def ask_augment_cohort(state: WizardState) -> PlanOptions | None:
    """Choose which CIKs this augmentation should consider requested.
    Every source is a *request* whose real work is decided by subtraction
    against the base.
    """
    return ask_cohort_source(state, purpose="Cohort to request")


def readable_sources(sources: list[SourceSummary]) -> list[SourceSummary]:
    """Source snapshots a comparison can actually be run against."""
    return [item for item in sources if item["readable"]]


def _refresh_source(state: WizardState) -> None:
    """Publish a source snapshot into the artifacts root this session is using.
    ``None`` would resolve the project default instead.
    """
    cmd_refresh(Path(state.artifacts_root) if state.artifacts_root else None)


def _offer_source_refresh(state: WizardState) -> bool:
    """Offer to publish a source snapshot when none is on disk yet.
    Defaults to no: publishing an unrequested immutable snapshot outlives the session.
    """
    print(
        "\nNo SEC listing source snapshot is published, so a curated seed cannot be "
        "projected against active listings."
    )
    if not confirm_network("Fetch the live SEC company ticker listing now? (y/N) "):
        print("cancelled; the seed alone can still be used as a cohort")
        return False
    _refresh_source(state)
    return True


def _resolve_source_roster(
    state: WizardState, seed: str, sources: list[SourceSummary]
) -> str:
    """Resolve the effective roster for a seed and a source snapshot.
    A pure projection of two immutable files, reused when already compared.
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
