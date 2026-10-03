"""Rendering the distributed lifecycle as copy-pasteable shell commands.

Printing the commands matters because the alternative is remembering the flags: a
worker handed the wrong arguments runs chunks it was never assigned, and the
failure looks like a data problem rather than a mistyped one.

This is separate from the wizard because it is not a wizard concern. It needs an
assignment division and a plan summary, and it needs nothing from the session
except which plan is resolved -- so it takes those as arguments instead of
importing the operator, and the operator hands them over.

The sequence printed here is the one the pipeline actually implements, and every
step is important. ``export`` copies the bundle out; each machine runs
``worker`` against its own bundle; the coordinator must ``import`` each returned
bundle through the trust boundary before ``merge`` will see those chunks. Emitting
export/worker/merge and omitting ``import`` produced a workflow whose final
command silently merged nothing, because the returned chunks were never adopted.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from edgar_sec.foundation.runtime.interactive import prompt_text

from .assignment import divide_chunks
from .discovery import plan_summary
from .paths import MetadataPaths

__all__ = ["render_worker_commands", "shell_arg"]


def shell_arg(value: str) -> str:
    """Quote one emitted argument so a destination with spaces stays executable.

    The commands below are meant to be copied and pasted, so a destination chosen
    as ``distrib/q3 run`` must survive the shell rather than becoming two
    arguments and a parse error on the receiving machine.
    """
    if value and all(char not in value for char in " \t\n\"'\\$`*?[]{}();&|<>#~!()"):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def render_worker_commands(
    metadata: MetadataPaths,
    resolve_plan_id: Callable[[], str | None],
) -> None:
    """Print the distributed lifecycle for the resolved plan, in execution order.

    ``resolve_plan_id`` returns the plan this session is working on, or ``None``
    when it could not be established. The caller owns that decision -- the wizard
    prompts and discovers -- so this function never asks a question it cannot
    justify, and a cancelled pick simply prints nothing.

    Worker ids and bundle names come from the same assignment division ``export``
    uses, and workers with no chunk are not listed, so the printed set matches the
    directories the export will actually create.
    """
    plan_id = resolve_plan_id()
    if not plan_id:
        return
    summary = plan_summary(metadata, plan_id)
    if not summary["readable"]:
        print(f"plan {plan_id} is unreadable; run status for why, then plan again")
        return

    workers = _ask_int("Number of worker bundles", 2) or 2
    destination = prompt_text("Destination directory", f"distrib/{plan_id[:8]}").strip()
    if not destination:
        return
    dest = Path(destination)
    try:
        assignments = divide_chunks(summary["chunk_count"], workers)
    except ValueError as exc:
        print(f"cannot divide this plan across {workers} workers: {exc}")
        return
    assigned = [
        (worker_id, dest / worker_id) for worker_id, ids in assignments.items() if ids
    ]

    print("\nCoordinator (run this first):")
    print(
        "  python run.py metadata export"
        f" --plan-id {shell_arg(plan_id)}"
        f" --worker-count {workers}"
        f" --destination {shell_arg(destination)}"
    )
    for index, (worker_id, bundle) in enumerate(assigned, start=1):
        print(f"\nMachine {index} ({worker_id}):")
        print(
            "  python run.py metadata worker"
            f" --bundle {shell_arg(str(bundle))}"
            f" --worker {shell_arg(worker_id)}"
        )
    print("\nCoordinator, once every bundle has come back:")
    for _, bundle in assigned:
        print(
            "  python run.py metadata import"
            f" --plan-id {shell_arg(plan_id)}"
            f" --source {shell_arg(str(bundle))}"
        )
    print("\nCoordinator, once the imports are done:")
    print(f"  python run.py metadata merge --plan-id {shell_arg(plan_id)}")


def _ask_int(label: str, default: int | None = None) -> int | None:
    answer = prompt_text(label, "" if default is None else str(default)).strip()
    if not answer:
        return None
    try:
        return int(answer)
    except ValueError:
        print(f"'{answer}' is not a whole number; using the configured default")
        return None
