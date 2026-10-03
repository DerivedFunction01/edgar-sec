"""Interactive terminal operator for the metadata sync pipeline.

The wizard is a thin presentation layer over the same typed options and the same
command functions the CLI uses, so the two surfaces cannot drift. What it adds is
*discovery*: it looks at what is already on disk, shows the active plan and the
current snapshot before each menu, carries that state across visits, and offers a
numbered pick instead of asking the operator to remember an identifier.

Discovery also keeps every identifier derived rather than typed. A plan comes
from a listing, the augmentation's published snapshot id defaults to its derived
delta plan id, and the current-snapshot pointer is moved by an explicit operation
over an already-published manifest. The one identifier a menu asks for is the
target-plan path, which is deliberately a cross-pipeline handoff rather than a
discovery surface.

State is passed in rather than held in a module global so the actions close over
it and a test can drive the whole wizard without a terminal or a leaked session.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    operator_entrypoint,
    prompt_text,
)
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings

from .cli import (
    cmd_compare,
    cmd_export,
    cmd_merge,
    cmd_plan,
    cmd_refresh,
    cmd_run,
    cmd_status,
    cmd_worker,
)
from .cli import main as cli_main
from .discovery import (
    current_snapshot_id,
    describe_roster,
    list_plans,
    list_rosters,
    list_snapshots,
    list_source_snapshots,
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
from .source_registry import SOURCE_NAME

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

# Fetching from SEC is the long, rate-limited, network-touching part of this
# pipeline. Confirmation defaults to no: an accidental yes costs wall-clock and
# request budget, an accidental no costs one keypress.
NETWORK_PROMPT = "This contacts SEC over the network. Continue? (y/N) "


@dataclass
class WizardState:
    """What the operator has already established, carried across menu visits.

    The state attributes make it inspectable, allowing tests to drive the wizard
    without a terminal.

    ``artifacts_root`` is the session's root, or empty for the configured project
    default. No menu action asks for it: the question already has one authority --
    the registered ``artifacts.root`` setting that ``resolve_paths()`` reads -- and
    every action routes through this one field, so a caller can scope a whole
    session to another tree without any action prompting for it. A non-default root
    for a single command is ``--artifacts`` on the subcommands instead.
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
    """One line describing what this session is currently pointed at.

    Shown above every menu, so an operator can see the working plan and the
    published snapshot without having to run status first. A session with
    nothing resolved says so and points at the action that creates it, rather
    than leaving a blank where a plan id belongs.
    """
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

    ``None`` is the signal to resolve one rather than to act on a guess, so an
    action is never performed against an unidentified plan.
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

    A single plan is adopted without asking. Several are offered as a numbered
    list, newest first. None is reported as a reason -- including that a
    published snapshot exists -- so the operator is told what to do next instead
    of watching a prompt do nothing.
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
        # Adopting it would point every later action at a plan this build cannot
        # load. Report why and leave the session unresolved so the operator is
        # told to plan again rather than silently acting on nothing.
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
    """Resolve a plan before an action, so no action is ever a silent no-op.

    Reuses what the session already established, otherwise discovers what is on
    disk, and only then asks the operator.
    """
    if state.plan_id:
        return True
    return resolve_plan(state)


def select_snapshot(state: WizardState) -> None:
    """Point ``current`` at a published snapshot, including an earlier one.

    A merge advances the pointer as a side effect, so without this the pointer can
    only ever move forward and a reader cannot be sent back to a snapshot that is
    still on disk. Selecting one is a pointer move only: no snapshot is written,
    removed, or republished, and the next successful merge advances it again.
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


def _ask_cohort_source(state: WizardState) -> tuple[str, str] | None:
    """Choose the cohort a plan is built over: a curated CSV or a published roster.

    A roster is what ``sources compare`` publishes, and it is a content address over
    one source snapshot plus one curated input, so it is the durable form of a
    cohort. Prompting only for a CSV made that workflow unreachable from the menu:
    the operator ran a comparison, produced a roster, and was then asked for a file
    instead.

    Returns ``(input_path, registry_id)`` with exactly one of the two set, or
    ``None`` to cancel. The CSV is offered first and stays the default, so the
    common case is unchanged; the roster list is appended only when one exists.
    """
    source = prompt_text("CIK manifest CSV (blank = cancel)", DEFAULT_INPUT)
    if not source:
        return None
    rosters = list_rosters(state.metadata())
    if not rosters:
        return source, ""

    print("\nCohort sources:")
    print(f"  1. {source}  (curated manifest CSV)")
    for index, roster in enumerate(rosters, start=2):
        print(f"  {index}. {describe_roster(roster)}")
    raw = prompt_text("Cohort source number", "1").strip() or "1"
    try:
        choice = int(raw)
    except ValueError:
        choice = 1
    if choice == 1:
        return source, ""
    if not 2 <= choice <= len(rosters) + 1:
        print("invalid selection; using the curated manifest CSV")
        return source, ""
    chosen = rosters[choice - 2]
    if not chosen["readable"]:
        print(
            f"{chosen['registry_id']} cannot be planned from: {chosen['readable_reason']}"
        )
        return source, ""
    return "", str(chosen["registry_id"])


def _ask_plan_options(
    state: WizardState, *, with_limit: bool = False
) -> PlanOptions | None:
    """Collect the cohort reference and chunk layout a plan needs."""
    cohort = _ask_cohort_source(state)
    if cohort is None:
        return None
    input_path, registry_id = cohort
    settings = resolve_runtime_settings()
    chunk_size = _ask_int(
        "CIKs per chunk (blank = configured default)", settings.default_chunk_size
    )
    limit = _ask_int("Limit CIKs (blank = all)") if with_limit else None
    return plan_options(
        input_path=input_path or None,
        registry_id=registry_id,
        chunk_size=chunk_size,
        limit=limit,
    )


def _ask_run_options(
    state: WizardState, *, with_bundle: bool = False
) -> RunOptions | None:
    """Collect the plan reference a status/run/merge invocation needs.

    A blank plan id falls back to the session's plan and then to discovery,
    rather than returning nothing — a blank answer that returned to the menu
    having done nothing reads as a broken pipeline rather than a missing plan. A
    copied bundle names its own plan, so a worker is never asked what it is
    already holding.
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
    # The session should act on the plan it just created rather than asking the
    # operator to name it back.
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
    """Add the CIKs a chosen cohort has and the base snapshot lacks.

    The journey itself -- which source observations exist, which cohort to
    request, which snapshot to build on, and what the delta would be -- lives in
    ``augment_flow``. It is split out because it is the only action needing a
    source snapshot, a base snapshot, and a preflight, and folding it back in here
    put two unrelated surfaces in one file.
    """
    from .augment_flow import run_augment

    run_augment(state)


def export(state: WizardState) -> None:
    if not _ensure_plan(state):
        return
    destination = prompt_text("Destination directory", "").strip()
    if not destination:
        print("cancelled; export needs a destination directory")
        return
    worker_count = _ask_int("Worker assignments to emit", 2)
    if worker_count is None:
        print("cancelled; export needs a worker count")
        return
    cmd_export(
        state.run_options(),
        worker_count=worker_count,
        destination=Path(destination).resolve(),
    )


def worker(state: WizardState) -> None:
    options = _ask_run_options(state, with_bundle=True)
    if options is None:
        return
    label = prompt_text("Worker id (blank = the only assignment)", "").strip()
    if label:
        options.worker_id = label
    if not confirm_network():
        print("cancelled; nothing was fetched")
        return
    cmd_worker(options)


def refresh(state: WizardState) -> None:
    if not confirm_network("This fetches the SEC listing source. Continue? (y/N) "):
        print("cancelled; nothing was fetched")
        return
    cmd_refresh(Path(state.artifacts_root) if state.artifacts_root else None)


def compare(state: WizardState) -> None:
    """Compare a curated seed against a published SEC listing snapshot.

    This is the explicit form of what augmentation now does for you. It used to
    list published *metadata* snapshots under a "Source snapshots" heading and
    then resolve a source manifest from that id, so the command could not have
    worked: the two namespaces are different directories and a metadata snapshot
    id is never a source snapshot id.
    """
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


def commands(state: WizardState) -> None:
    """Print the full distributed lifecycle for this plan, in execution order.

    Renders a shell command per machine based on chunk assignment division,
    preventing manual flag transcription errors.
    """
    from .worker_commands import render_worker_commands

    render_worker_commands(
        state.metadata(), lambda: state.plan_id if _ensure_plan(state) else None
    )


# ----------------------------------------------------------------------- menu


def build_operator_menu(state: WizardState | None = None) -> tuple[MenuAction, ...]:
    """Build the operator actions, bound to this session's state."""
    session = state if state is not None else WizardState()
    return (
        MenuAction("1", "Plan generation", lambda: plan(session)),
        MenuAction("2", "Status and resume inspect", lambda: status(session)),
        MenuAction("3", "Run chunks", lambda: run(session)),
        MenuAction("4", "Merge chunks into snapshot", lambda: merge(session)),
        MenuAction("5", "Augment published snapshot", lambda: augment(session)),
        MenuAction("6", "Export bundles for workers", lambda: export(session)),
        MenuAction("7", "Run a worker bundle", lambda: worker(session)),
        MenuAction("8", "Refresh external source", lambda: refresh(session)),
        MenuAction(
            "9", "Compare curated input against a source", lambda: compare(session)
        ),
        MenuAction(
            "p",
            "Switch the current published snapshot",
            lambda: select_snapshot(session),
        ),
        MenuAction(
            "c", "Show worker commands for this plan", lambda: commands(session)
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
