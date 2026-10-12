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
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.foundation.runtime.settings.validators import positive_int_type
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
        target_id = prompt_text("Target ID (optional)").strip()
        if target_id:
            args.extend(("--target-id", target_id))
    cli_main(args)


def _configured_response_byte_limit() -> int:
    settings = resolve_settings(include=("acquisition",))
    return positive_int_type(str(settings["acquisition.max_response_bytes"]))


def _action_run() -> None:
    run_id = prompt_text("Projected S9 run ID").strip()
    if not run_id:
        print("Acquisition cancelled.")
        return
    try:
        default_limit = _configured_response_byte_limit()
    except (KeyError, TypeError, ValueError) as error:
        print(
            f"Acquisition cancelled: invalid configured response-byte limit ({error})."
        )
        return
    response_limit = prompt_text(
        "Maximum decoded response bytes", str(default_limit)
    ).strip()
    try:
        effective_limit = positive_int_type(response_limit or str(default_limit))
    except ValueError:
        print("Acquisition cancelled: enter a positive response-byte limit.")
        return
    retry = prompt_text("Retry eligible failed targets? (yes/no)", "no").strip().lower()
    if retry not in {"yes", "no"}:
        print("Acquisition cancelled: answer yes or no for retry selection.")
        return
    retain = (
        prompt_text("Retain raw response evidence? (yes/no)", "no").strip().lower()
        or "no"
    )
    if retain not in {"yes", "no"}:
        print("Acquisition cancelled: answer yes or no for response retention.")
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
        str(effective_limit),
    ]
    if retry == "yes":
        args.append("--retry-failures")
    if retain == "yes":
        args.append("--retain-response-evidence")
    cli_main(args)


def _action_process() -> None:
    run_id = prompt_text("Acquisition run ID").strip()
    if not run_id:
        print("Processing cancelled: run ID is required.")
        return
    retry = prompt_text("Retry failed processing targets? (yes/no)", "no")
    retry = retry.strip().lower()
    if retry not in {"yes", "no"}:
        print("Processing cancelled: answer yes or no for retry selection.")
        return
    args = ["process", "--run-id", run_id]
    if retry == "yes":
        args.append("--retry-failures")
    cli_main(args)


def _action_fixture_create() -> None:
    fixture_id = prompt_text("Fixture ID").strip()
    if not fixture_id:
        print("Fixture creation cancelled.")
        return
    cli_main(["fixture", "create", "--fixture", fixture_id])


def _action_fixture_fill() -> None:
    fixture_id = prompt_text("Fixture ID").strip()
    run_id = prompt_text("Run ID").strip()
    target_id = prompt_text("Target ID").strip()
    attempt_id = prompt_text("Attempt ID").strip()
    if not all((fixture_id, run_id, target_id, attempt_id)):
        print("Fixture fill cancelled: all IDs are required.")
        return

    try:
        default_limit = _configured_response_byte_limit()
    except (KeyError, TypeError, ValueError) as error:
        print(
            f"Fixture fill cancelled: invalid configured response-byte limit ({error})."
        )
        return
    response_limit = prompt_text(
        "Maximum response bytes to retain", str(default_limit)
    ).strip()
    try:
        response_limit_bytes = positive_int_type(response_limit or str(default_limit))
    except ValueError:
        print("Fixture fill cancelled: enter a positive response-byte limit.")
        return

    confirm = (
        prompt_text("Retain local response evidence in the fixture? (yes/no)", "no")
        .strip()
        .lower()
    )
    if confirm != "yes":
        print("Fixture fill cancelled; no evidence was retained.")
        return

    cli_main(
        [
            "fixture",
            "fill",
            "--fixture",
            fixture_id,
            "--run-id",
            run_id,
            "--target-id",
            target_id,
            "--attempt-id",
            attempt_id,
            "--max-response-bytes",
            str(response_limit_bytes),
        ]
    )


def _action_fixture_list() -> None:
    fixture_id = prompt_text("Fixture ID filter (optional)").strip()
    capture_id = prompt_text("Capture ID filter (optional)").strip()
    target_id = prompt_text("Target ID filter (optional)").strip()
    args = ["fixture", "list"]
    for option, value in (
        ("--fixture", fixture_id),
        ("--capture-id", capture_id),
        ("--target-id", target_id),
    ):
        if value:
            args.extend((option, value))
    cli_main(args)


def _action_fixture_replay() -> None:
    fixture_id = prompt_text("Fixture ID").strip()
    capture_id = prompt_text("Capture ID").strip()
    target_id = prompt_text("Target ID").strip()
    output_path = prompt_text("New replay output path").strip()
    if not all((fixture_id, capture_id, target_id, output_path)):
        print("Fixture replay cancelled: all IDs and an output path are required.")
        return

    confirm = prompt_text("Write replay output to this path? (yes/no)", "no")
    if confirm.strip().lower() != "yes":
        print("Fixture replay cancelled; no output was written.")
        return

    cli_main(
        [
            "fixture",
            "replay",
            "--fixture",
            fixture_id,
            "--capture-id",
            capture_id,
            "--target-id",
            target_id,
            "--output",
            output_path,
        ]
    )


def _action_review_generate() -> None:
    fixture_id = prompt_text("Fixture ID").strip()
    if not fixture_id:
        print("Review generation cancelled: fixture ID is required.")
        return
    args = ["review", "generate", "--fixture", fixture_id]
    capture_id = prompt_text("Capture ID filter (optional)").strip()
    target_id = prompt_text("Target ID filter (optional)").strip()
    output = prompt_text("Review output directory (optional)").strip()
    if capture_id:
        args.extend(("--capture-id", capture_id))
    if target_id:
        args.extend(("--target-id", target_id))
    if output:
        args.extend(("--output", output))
    cli_main(args)


def _action_review_compare() -> None:
    base = prompt_text("Base review run directory").strip()
    new = prompt_text("New review run directory").strip()
    if not all((base, new)):
        print("Review comparison cancelled: both run directories are required.")
        return
    cli_main(["review", "compare", "--base", base, "--new", new])


def build_operator_menu() -> tuple[MenuAction, ...]:
    return build_menu(
        menu_action("Project a target plan", _action_project),
        menu_action("Inspect acquisition runs", _action_status),
        menu_action("Run acquisition (live SEC; confirmation required)", _action_run),
        menu_action("Process acquired bodies", _action_process),
        _action("publish", "Publish snapshot (S11 gate)"),
        menu_action("Create local fixture", _action_fixture_create),
        menu_action(
            "Fill local fixture evidence (confirmation required)",
            _action_fixture_fill,
        ),
        menu_action("List local fixtures", _action_fixture_list),
        menu_action(
            "Replay local fixture (confirmation required)", _action_fixture_replay
        ),
        menu_action("Generate review artifacts", _action_review_generate),
        menu_action("Compare review runs", _action_review_compare),
        _action("snapshot status", "Snapshot status/evidence audit (S11 gate)"),
    )


def main(argv: list[str] | None = None) -> int:
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
