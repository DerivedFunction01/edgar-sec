"""Interactive entrypoint for acquisition command tracks."""

from __future__ import annotations

import sys

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_text,
)
from edgar_sec.pipelines.document_acquisition.cli import (
    main as cli_main,
    report_not_implemented,
)

MENU_TITLE = "Document Acquisition"


def _action(command: str, track: str) -> MenuAction:
    return menu_action(
        track,
        lambda: report_not_implemented(command),
    )


def _action_project() -> None:
    plan_id = prompt_text("Published S6 target-plan ID").strip()
    if not plan_id:
        print("Projection cancelled.")
        return
    cli_main(["project", "--plan-id", plan_id])


def _action_status() -> None:
    run_id = prompt_text("Run ID (blank lists all runs)").strip()
    args = ["status"]
    if run_id:
        args.extend(("--run-id", run_id))
    cli_main(args)


def _action_run() -> None:
    run_id = prompt_text("Projected S9 run ID").strip()
    if not run_id:
        print("Acquisition cancelled.")
        return
    response_limit = prompt_text("Maximum decoded response bytes").strip()
    if not response_limit.isdigit() or int(response_limit) < 1:
        print("Acquisition cancelled: enter a positive response-byte limit.")
        return
    retry = prompt_text("Retry eligible failed targets? (yes/no)", "no").strip().lower()
    if retry not in {"yes", "no"}:
        print("Acquisition cancelled: answer yes or no for retry selection.")
        return
    confirm = (
        prompt_text("Allow live SEC network access? (yes/no)", "no").strip().lower()
    )
    if confirm != "yes":
        print("Acquisition cancelled; no network request was made.")
        return
    args = [
        "run",
        "--run-id",
        run_id,
        "--max-response-bytes",
        str(int(response_limit)),
    ]
    if retry == "yes":
        args.append("--retry-failures")
    cli_main(args)


def build_operator_menu() -> tuple[MenuAction, ...]:
    return build_menu(
        menu_action("Project a target plan", _action_project),
        menu_action("Inspect acquisition runs", _action_status),
        menu_action("Run acquisition (live SEC; confirmation required)", _action_run),
        _action("process", "Process acquired bodies (not implemented)"),
        _action("publish", "Publish snapshot (S11 gate)"),
        _action("fixture list", "S9 fixtures console (capture, list, replay)"),
        _action("review build", "Review artifact console (build, compare)"),
        _action("snapshot status", "Snapshot status/evidence audit (S11 gate)"),
    )


def main(argv: list[str] | None = None) -> int:
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
