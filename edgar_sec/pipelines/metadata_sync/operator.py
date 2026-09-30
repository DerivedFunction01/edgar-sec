"""Interactive terminal operator for the metadata sync pipeline.

The wizard is a thin presentation layer over the same typed options and the same
command functions the CLI uses, so the two surfaces cannot drift. What it adds is
*discovery*: it looks at what is already on disk, shows the active plan before
each menu, carries that state across visits, and offers a numbered pick instead
of asking the operator to remember an identifier they were never shown.

That is the capability v1 had and v2 dropped. v1 ran an ``ensure_plan`` step at
the top of every loop iteration, so it could auto-resume an in-progress run,
adopt an existing plan, and offer regeneration on a stale one. v2 re-prompted
for a plan id every time and a blank answer did nothing, which made a pipeline
with a plan file on disk feel like a hand-typed CLI.

Restoring this here rather than in shared infrastructure is deliberate.
``roadmap/refactor_v2/v2_refactor_roadmap.md`` records why v1's equivalent was
not kept: the shared ``run_interactive`` "hardcoded Phase 01's exact model ...
[and] became dead code outside Phase 01". What is genuinely shared -- entrypoint
policy, terminal prompting, the manifest scan behind ``discovery`` -- is consumed
from ``foundation.runtime.interactive`` and ``infra.storage.manifests`` instead
of being rewritten here.

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
    cmd_augment,
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
    list_plans,
    list_snapshots,
    plan_summary,
    resolve_plan_choice,
)
from .options import (
    PlanOptions,
    RunOptions,
    derive_plan_id,
    plan_options,
    read_bundle_plan_id,
    run_options,
)
from .paths import resolve_metadata_paths

__all__ = [
    "WizardState",
    "build_operator_menu",
    "confirm_network",
    "main",
    "render_plan_header",
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

    v1 held this in a closure mutated by every action. The same values as
    attributes make it inspectable, which is what lets the tests drive the
    wizard without a terminal.
    """

    plan_id: str = ""
    bundle_root: str = ""
    worker_id: str = ""
    input_path: str = ""
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
                "Next: 1 Plan generation, 2 Augment, 3 Status, 0 Exit", "1"
            ).strip()
        else:
            print("\nNo plan on disk yet.")
            choice = prompt_text("Next: 1 Plan generation, 0 Exit", "1").strip()
        if choice == "2":
            augment(state)
        elif choice == "3":
            status(state)
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
    state.plan_id = chosen["plan_id"]
    state.bundle_root = ""
    print(f"Working plan: {chosen['plan_id']}")
    return True


def _ensure_plan(state: WizardState) -> bool:
    """Resolve a plan before an action, so no action is ever a silent no-op.

    Mirrors v1's ``ensure_plan``: reuse what the session already established,
    otherwise discover what is on disk, and only then ask.
    """
    if state.plan_id:
        return True
    return resolve_plan(state)


def _ask_plan_options(*, with_limit: bool = False) -> PlanOptions | None:
    """Collect the cohort reference and chunk layout a plan needs."""
    source = prompt_text("CIK manifest CSV (blank = cancel)", DEFAULT_INPUT)
    if not source:
        return None
    settings = resolve_runtime_settings()
    chunk_size = _ask_int(
        "CIKs per chunk (blank = configured default)", settings.default_chunk_size
    )
    limit = _ask_int("Limit CIKs (blank = all)") if with_limit else None
    return plan_options(input_path=source, chunk_size=chunk_size, limit=limit)


def _ask_run_options(
    state: WizardState, *, with_bundle: bool = False
) -> RunOptions | None:
    """Collect the plan reference a status/run/merge invocation needs.

    A blank plan id falls back to the session's plan and then to discovery,
    rather than returning nothing. That fallback is the regression this module
    exists to remove: a blank answer used to return to the menu having done
    nothing at all, which reads as a broken pipeline rather than a missing plan.
    A copied bundle names its own plan, so a worker is never asked what it is
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
    options = _ask_plan_options(with_limit=True)
    if options is None:
        return
    cmd_plan(options)
    # The session should act on the plan it just created rather than asking the
    # operator to name it back.
    state.plan_id = derive_plan_id(options)
    state.bundle_root = ""
    state.input_path = str(options.input_path or "")


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
    options = _ask_plan_options()
    if options is None:
        return
    base = prompt_text(
        "Base snapshot id", current_snapshot_id(state.metadata())
    ).strip()
    if not base:
        print("cancelled; an augment needs a base snapshot id")
        return
    new = prompt_text("New snapshot id", "").strip()
    if not new:
        print("cancelled; an augment needs a new snapshot id")
        return
    if not confirm_network("This fetches the delta from SEC. Continue? (y/N) "):
        print("cancelled; nothing was fetched")
        return
    cmd_augment(
        options,
        base_snapshot_id=base,
        new_snapshot_id=new,
        workers=_ask_int("Worker threads (blank = machine-derived)"),
    )


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
    artifacts = prompt_text("Artifacts root (blank = project default)", "").strip()
    if not confirm_network("This fetches the SEC listing source. Continue? (y/N) "):
        print("cancelled; nothing was fetched")
        return
    cmd_refresh(Path(artifacts) if artifacts else None)


def compare(state: WizardState) -> None:
    source = prompt_text("CIK manifest CSV", state.input_path or DEFAULT_INPUT)
    if not source:
        return
    manifests = list_snapshots(state.metadata())
    if not manifests:
        print("no source snapshot published; run 'Refresh external source' first")
        return
    print("\nSource snapshots:")
    for index, item in enumerate(manifests, start=1):
        print(f"  {index}. {item.get('snapshot_id', '?')}")
    answer = prompt_text("Source snapshot number", "1").strip() or "1"
    try:
        chosen = manifests[int(answer) - 1]
    except (ValueError, IndexError):
        print("invalid selection")
        return
    artifacts = prompt_text("Artifacts root (blank = project default)", "").strip()
    cmd_compare(
        plan_options(input_path=source, artifacts_root=artifacts or None),
        source_manifest=Path(str(chosen.get("manifest_path", ""))).resolve(),
    )


def commands(state: WizardState) -> None:
    """Print copy-pasteable commands for distributing this plan across machines.

    v1 rendered a command per machine from the operator menu. It matters because
    the alternative is remembering the flags, and a worker given the wrong
    arguments runs chunks it was not assigned.
    """
    if not _ensure_plan(state):
        return
    workers = _ask_int("Number of worker bundles", 2) or 2
    plan_id = state.plan_id
    destination = prompt_text("Destination directory", f"distrib/{plan_id[:8]}").strip()
    if not destination:
        return
    print("\nCoordinator (run this first):")
    print(
        f"  python run.py metadata export --plan-id {plan_id}"
        f" --workers {workers} --destination {destination}"
    )
    for index in range(1, workers + 1):
        print(f"\nMachine {index}:")
        print(
            f"  python run.py metadata worker --bundle {destination}/worker-{index}"
            f" --worker-id worker-{index}"
        )
    print("\nCoordinator, once the workers return their bundles:")
    print(f"  python run.py metadata merge --plan-id {plan_id}")


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
            "p", "Show worker commands for this plan", lambda: commands(session)
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: interactive by default, CLI when given a command."""
    return operator_entrypoint(
        MENU_TITLE,
        build_operator_menu(),
        cli_main,
        argv,
        interrupted_message=INTERRUPTED_MESSAGE,
    )


if __name__ == "__main__":
    sys.exit(main())
