"""Interactive operator for the table classification pipeline."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    MenuSeparator,
    PickItem,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.foundation.runtime.render import KeyValueRow, render_output

from .cli import main as cli_main
from .options import SurfaceOptions
from .planner import PlanError, build_plan, read_plan
from .translator import plan_request_for, planning_triples

MENU_TITLE = "Table Classification"


@dataclass(slots=True)
class OperatorSession:
    """Selections carried across operator actions."""

    snapshot_id: str | None = None
    stratum: str | None = None
    plan_id: str | None = None

    def header(self) -> str:
        return (
            "Last selections: "
            f"snapshot={self.snapshot_id or 'unset'}, "
            f"stratum={self.stratum or 'unset'}, "
            f"plan={self.plan_id or 'unset'}"
        )


def _plan_ids(options: SurfaceOptions) -> list[str]:
    root = options.resolved_plans_root()
    if not root.is_dir():
        return []
    return sorted(
        entry.name for entry in root.iterdir() if (entry / "plan.json").is_file()
    )


def _action_translate(session: OperatorSession) -> None:
    triples = planning_triples(stratum=session.stratum)
    render_output(
        [
            KeyValueRow(
                "planning triples",
                ", ".join(
                    f"{t.role}:{t.type}:optional={str(t.optional).lower()}"
                    for t in triples
                )
                or "none declared",
            )
        ],
        title="registry exhibit targets, translated",
    )


def _action_plan(session: OperatorSession) -> None:
    snapshot = prompt_text("Source snapshot id", session.snapshot_id or "")
    accessions_text = prompt_text("Accessions (comma-separated)", "")
    accessions = tuple(
        part.strip() for part in accessions_text.split(",") if part.strip()
    )
    if not accessions:
        print("plan cancelled: no accessions given")
        return
    stratum = prompt_text("Stratum (blank for all)", session.stratum or "")
    session.snapshot_id = snapshot.strip() or None
    session.stratum = stratum.strip() or None
    paths = SurfaceOptions().classification_paths()
    try:
        request = plan_request_for(
            accessions,
            source_snapshot_id=session.snapshot_id,
            stratum=session.stratum,
        )
        result = build_plan(request, paths)
        plan = read_plan(paths, result.plan_id)
    except (ValueError, PlanError) as error:
        print(f"planning refused: {error}")
        return
    session.plan_id = plan.plan_id
    render_output(
        [
            KeyValueRow("plan", plan.plan_id),
            KeyValueRow("filings", str(len(plan.filings))),
            KeyValueRow("work items", str(len(plan.work_items))),
            KeyValueRow("path", str(result.root)),
        ],
        title="planned classification run",
    )


def _action_inspect(session: OperatorSession) -> None:
    options = SurfaceOptions()
    items = [PickItem(plan_id, plan_id, plan_id) for plan_id in _plan_ids(options)]
    if not items:
        print("no plan documents found; plan a run first")
        return
    chosen = prompt_paginated_choice(
        items, prompt_label="Select planned run", default=session.plan_id
    )
    if chosen is None:
        return
    plan_id = str(chosen.value)
    plan = read_plan(options.classification_paths(), plan_id)
    session.plan_id = plan_id
    render_output(
        [
            KeyValueRow("plan", plan.plan_id),
            KeyValueRow("snapshot", str(plan.provenance["source_snapshot_id"])),
            KeyValueRow("filings", str(len(plan.filings))),
            KeyValueRow("document targets", str(len(plan.document_targets))),
            KeyValueRow("work items", str(len(plan.work_items))),
        ],
        title="plan drill",
    )


def _action_status(session: OperatorSession) -> None:
    cli_main(["status"])


def _action_run(session: OperatorSession) -> None:
    if session.plan_id is None:
        print("no plan selected; plan or inspect a run first")
        return
    cli_main(["run", "--plan-id", session.plan_id])


def build_operator_menu(
    session: OperatorSession | None = None,
) -> tuple[MenuAction, ...]:
    """The operator menu: plan, drill, run, and status actions."""
    state = session or OperatorSession()
    return build_menu(
        MenuSeparator("Planning"),
        menu_action(
            "Translate registry exhibit targets", lambda: _action_translate(state)
        ),
        menu_action("Plan a classification run", lambda: _action_plan(state)),
        MenuSeparator("Planned runs"),
        menu_action("Drill into a planned run", lambda: _action_inspect(state)),
        menu_action("Run the selected plan", lambda: _action_run(state)),
        menu_action("Surface status", lambda: _action_status(state)),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the operator, or the CLI when arguments are given."""
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
