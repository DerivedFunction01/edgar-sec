"""Interactive terminal operator for the metadata sync pipeline.
A thin presentation layer over the same command functions the CLI uses, so the two
surfaces cannot drift; state is passed in, so a test can drive the wizard without
a terminal.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_text,
)
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings

from .cli import (
    cmd_compare,
    cmd_family_index,
    cmd_merge,
    cmd_plan,
    cmd_refresh,
    cmd_run,
    cmd_status,
)

from .cli import main as cli_main
from .discovery import (
    SourceSummary,
    current_snapshot_id,
    list_plans,
    list_snapshots,
    list_source_snapshots,
    list_universe_snapshots,
    plan_summary,
    resolve_plan_choice,
    resolve_snapshot_choice,
    resolve_source_choice,
)
from .merger import MergeError, publish_current_snapshot
from .options import (
    PlanOptions,
    RunOptions,
    derive_plan_id,
    plan_options,
    read_bundle_plan_id,
    run_options,
)
from .paths import resolve_metadata_paths
from .source_registry import SOURCE_NAME, SOURCE_UNIVERSE_NAME

__all__ = [
    "WizardState",
    "build_operator_menu",
    "confirm_network",
    "main",
    "render_plan_header",
    "render_session_header",
]

MENU_TITLE = "Metadata Sync (Phase 01)"

DEFAULT_INPUT = "uploads/cik-sec.csv"

INTERRUPTED_MESSAGE = (
    "Interrupted. Completed chunks are preserved and will be skipped on resume;"
    " nothing already fetched is discarded."
)

# Confirmation defaults to no: an accidental yes costs wall-clock and request
# budget, an accidental no costs one keypress.
NETWORK_PROMPT = "This contacts SEC over the network. Continue? (y/N) "


@dataclass
class WizardState:
    """What the operator has already established, carried across menu visits.
    ``artifacts_root`` is the session's single authority for the tree.
    """

    plan_id: str = ""
    bundle_root: str = ""
    worker_id: str = ""
    input_path: str = ""
    registry_id: str = ""
    artifacts_root: str = ""

    def metadata(self):
        """Metadata layout for the artifacts root this session is using."""
        return resolve_metadata_paths(self.artifacts_root or None)

    def run_options(self, *, workers: int | None = None) -> RunOptions:
        """Execution options for the plan this session is working on."""
        return run_options(
            plan_id=self.plan_id,
            bundle_root=self.bundle_root or None,
            worker_id=self.worker_id,
            artifacts_root=self.artifacts_root or None,
            workers=workers,
        )

    def clear(self) -> None:
        """Forget the plan reference, forcing re-resolution on the next action."""
        self.plan_id = ""
        self.bundle_root = ""
        self.worker_id = ""


def _ask_int(label: str, default: int | None = None) -> int | None:
    """Prompt for a whole number, deferring to the registry on a blank answer."""
    answer = prompt_text(label, "" if default is None else str(default)).strip()
    if not answer:
        return None
    try:
        return int(answer)
    except ValueError:
        print(f"'{answer}' is not a whole number; using the configured default")
        return None


def confirm_network(prompt: str = NETWORK_PROMPT) -> bool:
    """Ask before a live SEC request. Defaults to no."""
    return prompt_text(prompt.strip(), "n").strip().lower() in ("y", "yes")


def render_session_header(state: WizardState) -> str:
    """One line describing what this session is currently pointed at."""
    metadata = state.metadata()
    current = current_snapshot_id(metadata)
    parts: list[str] = []
    header = render_plan_header(state)
    if header:
        parts.append(header)
    else:
        parts.append("No plan selected")
    parts.append(f"current snapshot: {current}" if current else "no snapshot published")
    return "  |  ".join(parts)


def render_plan_header(state: WizardState) -> str | None:
    """Describe the working plan, or ``None`` when none is resolved yet.

    ``None`` is the signal to resolve one rather than act on a guess.
    """
    if not state.plan_id:
        return None
    try:
        summary = plan_summary(state.metadata(), state.plan_id)
    except OSError as exc:
        return f"plan {state.plan_id}: cannot read ({exc})"
    if not summary["readable"]:
        return f"plan {state.plan_id}: unreadable or not compatible with this build"
    completed = summary["completed_chunks"]
    progress = (
        f"{completed}/{summary['chunk_count']} chunks"
        if completed >= 0
        else "progress unknown"
    )
    published = " [published]" if summary["published"] else ""
    return (
        f"plan {summary['plan_id']}{published}  "
        f"{summary['row_count']:,} CIKs  {progress}"
    )


def resolve_plan(state: WizardState) -> bool:
    """Resolve the plan this session acts on, discovering rather than assuming.
    An unreadable plan is refused rather than adopted.
    """
    metadata = state.metadata()
    plans = list_plans(metadata)
    if not plans:
        current = current_snapshot_id(metadata)
        if current:
            print(f"\nNo plan on disk. Snapshot {current} is published.")
            choice = prompt_text(
                "Next: 1 Plan generation, 2 Augment, 3 Status, 4 Switch snapshot, 0 Exit",
                "1",
            ).strip()
        else:
            print("\nNo plan on disk yet.")
            choice = prompt_text("Next: 1 Plan generation, 0 Exit", "1").strip()
        if choice == "2":
            augment(state)
        elif choice == "3":
            status(state)
        elif choice == "4":
            select_snapshot(state)
        return False

    def select(lines: list[str]) -> str:
        print("\nPlans (newest first):")
        for line in lines:
            print(line)
        return prompt_text("Plan number", "1").strip()

    chosen = resolve_plan_choice(plans, select=select)
    if chosen is None:
        state.clear()
        return False
    if not chosen["readable"]:
        print(
            f"plan {chosen['plan_id']} is unreadable or not compatible with this "
            "build; use 'Plan generation' to create one this build can run"
        )
        return False
    state.plan_id = chosen["plan_id"]
    state.bundle_root = ""
    print(f"Working plan: {chosen['plan_id']}")
    return True


def _ensure_plan(state: WizardState) -> bool:
    """Resolve a plan before an action, so no action is ever a silent no-op."""
    if state.plan_id:
        return True
    return resolve_plan(state)


def select_snapshot(state: WizardState) -> None:
    """Point ``current`` at a published snapshot, including an earlier one.
    A merge only advances the pointer; this moves it back, writing nothing.
    """
    metadata = state.metadata()
    manifests = list_snapshots(metadata)
    if not manifests:
        print("no published snapshots; merge a plan first")
        return

    def select(lines: list[str]) -> str:
        print("\nPublished snapshots:")
        for line in lines:
            print(line)
        return prompt_text("Snapshot number (blank = keep current)", "").strip()

    chosen = resolve_snapshot_choice(
        manifests, current_snapshot_id(metadata), select=select
    )
    if not chosen:
        print("current snapshot unchanged")
        return
    try:
        publish_current_snapshot(metadata, chosen)
    except MergeError as exc:
        print(f"could not switch snapshot: {exc}")
        return
    print(f"current snapshot is now {chosen}")


def _ask_cohort_source(state: WizardState) -> PlanOptions | None:
    """Choose the cohort a plan is built over.

    The picker is shared with augmentation: the sources available are the same,
    so a choice meaningful for planning is meaningful for augmenting.
    """
    from .augment_flow import ask_cohort_source

    return ask_cohort_source(state, purpose="Cohort to plan over")


def _ask_plan_options(
    state: WizardState, *, with_limit: bool = False
) -> PlanOptions | None:
    """Collect the cohort reference and chunk layout a plan needs."""
    cohort = _ask_cohort_source(state)
    if cohort is None:
        return None
    settings = resolve_runtime_settings()
    chunk_size = _ask_int(
        "CIKs per chunk (blank = configured default)", settings.default_chunk_size
    )
    limit = _ask_int("Limit CIKs (blank = all)") if with_limit else None
    return replace(
        cohort,
        chunk_size=chunk_size if chunk_size is not None else cohort.chunk_size,
        limit=limit,
    )


def _ask_run_options(
    state: WizardState, *, with_bundle: bool = False
) -> RunOptions | None:
    """Collect the plan reference a status/run/merge invocation needs.
    Blank falls back to the session's plan and then to discovery.
    """
    if with_bundle:
        bundle = prompt_text("Plan bundle directory (blank = local plan)", "").strip()
        if bundle:
            state.bundle_root = bundle
            state.plan_id = state.plan_id or read_bundle_plan_id(bundle)
    typed = prompt_text("Plan id (blank = use the working plan)", state.plan_id).strip()
    if typed and typed != state.plan_id:
        state.plan_id = typed
        state.bundle_root = ""
    if not state.plan_id and not _ensure_plan(state):
        return None
    return state.run_options(
        workers=_ask_int("Worker threads (blank = machine-derived)")
    )


# --------------------------------------------------------------------- actions


def plan(state: WizardState) -> None:
    options = _ask_plan_options(state, with_limit=True)
    if options is None:
        return
    cmd_plan(options)
    # Act on the plan just created rather than making the operator name it back.
    state.plan_id = derive_plan_id(options)
    state.bundle_root = ""
    state.input_path = str(options.input_path or "")
    state.registry_id = options.registry_id


def status(state: WizardState) -> None:
    options = _ask_run_options(state)
    if options is not None:
        cmd_status(options)


def run(state: WizardState) -> None:
    options = _ask_run_options(state)
    if options is None:
        return
    chunks = prompt_text("Chunk ids (blank = all outstanding)", "").strip()
    if chunks:
        options.chunk_ids = tuple(
            int(value) for value in chunks.replace(" ", "").split(",") if value
        )
    if not confirm_network():
        print("cancelled; nothing was fetched")
        return
    cmd_run(options)


def merge(state: WizardState) -> None:
    options = _ask_run_options(state)
    if options is not None:
        cmd_merge(options)


def augment(state: WizardState) -> None:
    from .augment_flow import run_augment

    run_augment(state)


def _source_label(source_name: str, snapshots: list[SourceSummary]) -> str:
    """One line naming a source and what is already published from it."""
    if not snapshots:
        return f"{source_name}  (not published)"
    newest = snapshots[0]
    return (
        f"{source_name}  ({newest['unique_cik_count']:,} CIKs published, retrieved "
        f"{newest['retrieved_at'] or 'unknown'})"
    )


def refresh(state: WizardState) -> None:
    """Publish an immutable snapshot of an external SEC source.

    Which source is asked, because the two differ in kind and size: the ticker
    listing is small, the registrant index large.
    """
    metadata = state.metadata()
    options = [
        (
            _source_label(SOURCE_NAME, list_source_snapshots(metadata, SOURCE_NAME)),
            SOURCE_NAME,
        ),
        (
            _source_label(SOURCE_UNIVERSE_NAME, list_universe_snapshots(metadata)),
            SOURCE_UNIVERSE_NAME,
        ),
    ]
    print("\nSource to refresh:")
    for index, (label, _name) in enumerate(options, start=1):
        print(f"  {index}. {label}")
    answer = prompt_text("Source number", "1").strip() or "1"
    try:
        choice = int(answer)
    except ValueError:
        choice = 1
    if not 1 <= choice <= len(options):
        print("invalid selection")
        return

    _label, source_name = options[choice - 1]
    approx = "~40 MB" if source_name == SOURCE_UNIVERSE_NAME else "~1 MB"
    if not confirm_network(
        f"Fetching {source_name} ({approx}) from SEC. Continue? (y/N) "
    ):
        print("cancelled; nothing was fetched")
        return
    cmd_refresh(
        Path(state.artifacts_root) if state.artifacts_root else None,
        source=source_name,
    )


def family_index(state: WizardState) -> None:
    """Assign a company family to every registrant of the published universe.

    Offline and derived, so it needs no confirmation. It is separate from the menu's
    other entries because only policy-scope planning consumes the result.
    """
    try:
        cmd_family_index(Path(state.artifacts_root) if state.artifacts_root else None)
    except FileNotFoundError as error:
        print(f"{error}")
        print("run 'Refresh external source' with cik_lookup first")


def compare(state: WizardState) -> None:
    """Compare a curated seed against a published SEC listing snapshot."""
    source = prompt_text("CIK manifest CSV", state.input_path or DEFAULT_INPUT)
    if not source:
        return
    metadata = state.metadata()
    sources = list_source_snapshots(metadata)
    if not sources:
        print("no source snapshot published; run 'Refresh external source' first")
        return

    def select(lines: list[str]) -> str:
        print("\nSource snapshots (newest first):")
        for line in lines:
            print(line)
        return prompt_text("Source snapshot number", "1").strip() or "1"

    chosen = resolve_source_choice(sources, select=select)
    if not chosen:
        print("cancelled; no source snapshot selected")
        return
    cmd_compare(
        plan_options(
            input_path=source,
            artifacts_root=Path(state.artifacts_root) if state.artifacts_root else None,
        ),
        source_manifest=metadata.source_manifest_file(SOURCE_NAME, chosen),
    )


def open_metadata_distrib_console(state: WizardState) -> None:
    """Launch the interactive worker distribution console."""
    from edgar_sec.infra.distribution.menu import DistribMenuConfig, run_distrib_menu
    from .distribution_adapter import MetadataDistributionAdapter

    adapter = MetadataDistributionAdapter(
        artifacts_root=Path(state.artifacts_root) if state.artifacts_root else None
    )
    config = DistribMenuConfig(
        adapter=adapter,
        plan_id_provider=lambda: state.plan_id if _ensure_plan(state) else None,
        title="Metadata Sync Worker Distribution",
    )
    run_distrib_menu(config)


def open_metadata_dag_console(state: WizardState) -> None:
    """Launch the interactive DAG lifecycle console for metadata sync snapshots."""
    from edgar_sec.infra.storage.dag.menu import DAGMenuConfig, run_dag_menu
    from .specs import METADATA_RELATION_SPECS

    config = DAGMenuConfig(
        snapshots_root=lambda: state.metadata().snapshots_root,
        title="Metadata Sync Snapshot DAG Console",
        specs=METADATA_RELATION_SPECS,
        publish_action=lambda: merge(state),
        publish_label="Merge completed run chunks and publish to DAG",
    )
    run_dag_menu(config)


# ----------------------------------------------------------------------- menu


def build_operator_menu(state: WizardState | None = None) -> tuple[MenuAction, ...]:
    """Build the operator actions, bound to this session's state."""
    session = state if state is not None else WizardState()
    return build_menu(
        menu_action("Plan generation", lambda: plan(session)),
        menu_action("Status and resume inspect", lambda: status(session)),
        menu_action("Run chunks", lambda: run(session)),
        menu_action("Augment published snapshot", lambda: augment(session)),
        menu_action("Refresh external source", lambda: refresh(session)),
        menu_action("Compare curated input against a source", lambda: compare(session)),
        menu_action(
            "Assign company families for the universe",
            lambda: family_index(session),
            key="f",
        ),
        menu_action(
            "Worker distribution console (export, worker, import, commands)",
            lambda: open_metadata_distrib_console(session),
            key="d",
        ),
        menu_action(
            "Snapshot DAG console (merge/publish, switch current, inspect, branches, tags)",
            lambda: open_metadata_dag_console(session),
            key="p",
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: interactive by default, CLI when given a command."""
    state = WizardState()
    return operator_entrypoint(
        MENU_TITLE,
        build_operator_menu(state),
        cli_main,
        argv,
        interrupted_message=INTERRUPTED_MESSAGE,
        before_menu=lambda: render_session_header(state),
    )


if __name__ == "__main__":
    sys.exit(main())
