"""Stable command surface for document acquisition tracks."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.pipelines.document_acquisition.commands.fixture import (
    cmd_fixture_capture,
    cmd_fixture_create,
    cmd_fixture_list,
    cmd_fixture_replay,
)
from edgar_sec.pipelines.document_acquisition.commands.project import cmd_project
from edgar_sec.pipelines.document_acquisition.commands.run import cmd_run
from edgar_sec.pipelines.document_acquisition.commands.status import cmd_status

__all__ = ["build_parser", "main", "report_not_implemented"]


_TRACKS = {
    "project": "S9 target-plan projection",
    "status": "S9 run-state inspection",
    "run": "S9 network acquisition",
    "process": "S10 body processing",
    "publish": "S11 Parquet/DAG publication",
    "fixture create": "S9 fixture initialization",
    "fixture capture": "S9 fixture capture",
    "fixture list": "S9 fixture discovery",
    "fixture replay": "S9 fixture replay",
    "review build": "S7 review artifact generation",
    "review compare": "S7 review comparison",
    "review list": "S7 review discovery",
    "snapshot status": "S11 snapshot availability",
    "snapshot audit": "S9/S10 evidence audit",
}


def report_not_implemented(command: str, *, json_output: bool = False) -> int:
    track = _TRACKS[command]
    message = "This command track is not implemented; no work was performed."
    status = "not_implemented"
    if command == "publish":
        message = (
            "S11 publication is gated on representative S9/S10 evidence and explicit "
            "approval; no work was performed."
        )
        status = "blocked_by_gate"
    elif command == "snapshot status":
        message = "No acquisition snapshot is published; S11 publication remains gated."
    elif command == "snapshot audit":
        message = (
            "No S9/S10 evidence audit is implemented; no snapshot was read or written."
        )
    result = {
        "command": command,
        "implemented": False,
        "message": message,
        "status": status,
        "track": track,
    }
    if json_output:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"not implemented: {track}; {message}", file=sys.stderr)
    return 2


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifacts", default=None, help="artifacts root override")
    parser.add_argument("--json", action="store_true", help="emit JSON to stdout")


def cmd_review_build(args: argparse.Namespace) -> int:
    return report_not_implemented("review build", json_output=args.json)


def cmd_review_compare(args: argparse.Namespace) -> int:
    return report_not_implemented("review compare", json_output=args.json)


def cmd_review_list(args: argparse.Namespace) -> int:
    return report_not_implemented("review list", json_output=args.json)


def cmd_snapshot_status(args: argparse.Namespace) -> int:
    return report_not_implemented("snapshot status", json_output=args.json)


def cmd_snapshot_audit(args: argparse.Namespace) -> int:
    return report_not_implemented("snapshot audit", json_output=args.json)


_TODO_HANDLERS = {
    "review build": cmd_review_build,
    "review compare": cmd_review_compare,
    "review list": cmd_review_list,
    "status": cmd_status,
    "snapshot status": cmd_snapshot_status,
    "snapshot audit": cmd_snapshot_audit,
}


def _set_todo(parser: argparse.ArgumentParser, command: str) -> None:
    parser.set_defaults(
        acquisition_command=command,
        func=_TODO_HANDLERS.get(command, _cmd_todo),
    )


def _cmd_todo(args: argparse.Namespace) -> int:
    return report_not_implemented(args.acquisition_command, json_output=args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acquisition",
        description="Project and operate on S9 acquisition runs.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    project = commands.add_parser("project", help="project a published S6 target plan")
    project.add_argument("--plan-id", required=True, help="published target-plan id")
    _add_output_options(project)
    project.set_defaults(func=cmd_project)

    status = commands.add_parser("status", help="inspect resumable acquisition runs")
    status.add_argument("--run-id", help="run identifier (default: list runs)")
    status.add_argument("--target-id", help="show attempts for one run target")
    _add_output_options(status)
    _set_todo(status, "status")

    run = commands.add_parser("run", help="acquire pending S9 target bodies")
    run.add_argument("--run-id", required=True, help="projected acquisition run id")
    run.add_argument("--retry-failures", action="store_true")
    run.add_argument("--retain-response-evidence", action="store_true")
    run.add_argument(
        "--workers",
        type=positive_int_type,
        help="upper bound clamped to resource capacity; acquisition runs serially",
    )
    run.add_argument(
        "--max-response-bytes",
        type=positive_int_type,
        help=(
            "finite decoded-response byte ceiling per SEC request "
            "(default: configured acquisition.max_response_bytes)"
        ),
    )
    run.add_argument("--confirm-stale-lock", action="store_true")
    _add_output_options(run)
    run.set_defaults(func=cmd_run)

    process = commands.add_parser("process", help="process acquired target bodies")
    process.add_argument("--run-id", required=True, help="acquisition run id")
    process.add_argument("--workers", type=positive_int_type)
    _add_output_options(process)
    _set_todo(process, "process")

    publish = commands.add_parser("publish", help="publish an approved S11 snapshot")
    publish.add_argument("--run-id", required=True, help="completed acquisition run id")
    publish.add_argument("--branch", default="main")
    publish.add_argument("--expected-branch-tip", default=None)
    _add_output_options(publish)
    _set_todo(publish, "publish")

    fixture = commands.add_parser("fixture", help="manage S9 response fixtures")
    fixture_commands = fixture.add_subparsers(dest="fixture_command", required=True)
    fixture_create = fixture_commands.add_parser("create", help="initialize a fixture")
    fixture_create.add_argument("--fixture-id", required=True)
    _add_output_options(fixture_create)
    fixture_create.set_defaults(func=cmd_fixture_create)
    fixture_capture = fixture_commands.add_parser(
        "capture", help="capture run responses"
    )
    fixture_capture.add_argument("--fixture-id", required=True)
    fixture_capture.add_argument("--run-id", required=True)
    fixture_capture.add_argument("--target-id", required=True)
    fixture_capture.add_argument("--attempt-id", required=True)
    fixture_capture.add_argument(
        "--max-response-bytes",
        type=positive_int_type,
        help="response byte ceiling (default: configured acquisition.max_response_bytes)",
    )
    _add_output_options(fixture_capture)
    fixture_capture.set_defaults(func=cmd_fixture_capture)
    fixture_list = fixture_commands.add_parser("list", help="list validated fixtures")
    fixture_list.add_argument("--fixture-id")
    fixture_list.add_argument("--capture-id")
    fixture_list.add_argument("--target-id")
    _add_output_options(fixture_list)
    fixture_list.set_defaults(func=cmd_fixture_list)
    fixture_replay = fixture_commands.add_parser(
        "replay", help="replay captured responses"
    )
    fixture_replay.add_argument("--fixture-id", required=True)
    fixture_replay.add_argument("--capture-id", required=True)
    fixture_replay.add_argument("--target-id", required=True)
    fixture_replay.add_argument("--output", required=True)
    _add_output_options(fixture_replay)
    fixture_replay.set_defaults(func=cmd_fixture_replay)

    review = commands.add_parser("review", help="build and compare review artifacts")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    review_build = review_commands.add_parser("build", help="build review artifacts")
    review_build.add_argument("--run-id", required=True)
    _add_output_options(review_build)
    _set_todo(review_build, "review build")
    review_compare = review_commands.add_parser("compare", help="compare review runs")
    review_compare.add_argument("--left", required=True)
    review_compare.add_argument("--right", required=True)
    _add_output_options(review_compare)
    _set_todo(review_compare, "review compare")
    review_list = review_commands.add_parser("list", help="list review runs")
    _add_output_options(review_list)
    _set_todo(review_list, "review list")

    snapshot = commands.add_parser("snapshot", help="inspect S11 status and evidence")
    snapshot_commands = snapshot.add_subparsers(dest="snapshot_command", required=True)
    for action in ("status", "audit"):
        snapshot_action = snapshot_commands.add_parser(action)
        _add_output_options(snapshot_action)
        _set_todo(snapshot_action, f"snapshot {action}")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
