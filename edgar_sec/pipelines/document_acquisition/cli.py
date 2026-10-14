"""Stable command surface for document acquisition tracks."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.pipelines.document_acquisition.commands.fixture import (
    cmd_fixture_create,
    cmd_fixture_fill,
    cmd_fixture_list,
)
from edgar_sec.pipelines.document_acquisition.commands.review import (
    cmd_review_analyze,
    cmd_review_artifacts,
    cmd_review_compare,
    cmd_review_holdout,
    cmd_review_label,
)
from edgar_sec.pipelines.document_acquisition.commands.project import cmd_project
from edgar_sec.pipelines.document_acquisition.commands.publish import cmd_publish
from edgar_sec.pipelines.document_acquisition.commands.run import cmd_run
from edgar_sec.pipelines.document_acquisition.commands.snapshot import (
    cmd_snapshot_list,
    cmd_snapshot_query,
    cmd_snapshot_status,
)
from edgar_sec.pipelines.document_acquisition.commands.status import cmd_status

__all__ = ["build_parser", "main", "report_not_implemented"]


_TRACKS = {
    "project": "S9 target-plan projection",
    "status": "S9 run-state inspection",
    "run": "S9 network acquisition",
    "publish": "S11 Parquet/DAG publication",
    "fixture create": "S9 fixture initialization",
    "fixture fill": "S9 fixture capture",
    "fixture list": "S9 fixture discovery",
    "review generate": "S7 review artifact generation",
    "review compare": "S7 review comparison",
    "review analyze": "S7 review-run analysis",
    "review label": "M8 exhibit label capture",
    "review holdout": "M8 issuer/time-separated exhibit evaluation",
    "snapshot status": "S11 snapshot availability",
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
    status.set_defaults(func=cmd_status)

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

    publish = commands.add_parser("publish", help="publish an approved S11 snapshot")
    publish.add_argument("--run-id", required=True, help="completed acquisition run id")
    publish.add_argument("--branch", default="main")
    publish.add_argument("--expected-branch-tip", default=None)
    publish.add_argument(
        "--allow-errors",
        action="store_true",
        help="allow publishing runs with non-fatal errors",
    )
    _add_output_options(publish)
    publish.set_defaults(func=cmd_publish)

    fixture = commands.add_parser("fixture", help="manage S9 parser-body fixtures")
    fixture_commands = fixture.add_subparsers(dest="fixture_command", required=True)
    fixture_create = fixture_commands.add_parser("create", help="initialize a fixture")
    fixture_create.add_argument("--fixture", required=True)
    fixture_create.add_argument("--plan-id", required=True)
    _add_output_options(fixture_create)
    fixture_create.set_defaults(func=cmd_fixture_create)
    fixture_fill = fixture_commands.add_parser(
        "fill", help="capture acquired selected bodies from a run"
    )
    fixture_fill.add_argument("--fixture", required=True)
    fixture_fill.add_argument("--run-id", required=True)
    fixture_fill.add_argument("--no-progress", action="store_true")
    _add_output_options(fixture_fill)
    fixture_fill.set_defaults(func=cmd_fixture_fill)
    fixture_list = fixture_commands.add_parser("list", help="list validated fixtures")
    fixture_list.add_argument("--fixture")
    _add_output_options(fixture_list)
    fixture_list.set_defaults(func=cmd_fixture_list)
    review = commands.add_parser(
        "review", help="generate, label, and evaluate offline review runs"
    )
    review_commands = review.add_subparsers(dest="review_command", required=True)
    review_generate = review_commands.add_parser(
        "generate", help="parse captured fixture bodies into review artifacts"
    )
    review_generate.add_argument("--fixture", required=True)
    review_generate.add_argument("--output")
    review_generate.add_argument("--limit", type=positive_int_type)
    review_generate.add_argument("--artifacts", dest="artifacts_root", default="")
    review_generate.add_argument("--json", action="store_true")
    review_generate.add_argument("--no-progress", action="store_true")
    review_generate.set_defaults(func=cmd_review_artifacts)

    review_compare = review_commands.add_parser(
        "compare", help="compare validated acquisition review runs"
    )
    review_compare.add_argument("--base", required=True)
    review_compare.add_argument("--new", required=True)
    review_compare.add_argument("--output")
    review_compare.add_argument("--max-display", type=positive_int_type, default=20)
    review_compare.add_argument("--artifacts", default="")
    review_compare.add_argument("--json", action="store_true")
    review_compare.set_defaults(func=cmd_review_compare)

    review_analyze = review_commands.add_parser(
        "analyze", help="validate and summarize offline acquisition review runs"
    )
    review_analyze.add_argument("--run", action="append", required=True)
    review_analyze.add_argument("--output")
    review_analyze.add_argument("--artifacts", default="")
    review_analyze.add_argument("--json", action="store_true")
    review_analyze.set_defaults(func=cmd_review_analyze)

    review_label = review_commands.add_parser(
        "label", help="record a pinned, immutable exhibit review label"
    )
    review_label.add_argument("--artifact", required=True)
    review_label.add_argument(
        "--outcome", required=True, choices=("positive", "negative", "ambiguous")
    )
    review_label.add_argument(
        "--observed-kind",
        required=True,
        choices=(
            "exhibit",
            "primary_report",
            "data_file",
            "graphic",
            "paper",
            "unknown",
        ),
    )
    review_label.add_argument("--observed-authority")
    review_label.add_argument("--observed-code")
    review_label.add_argument("--annotator-id", required=True)
    review_label.add_argument("--annotated-at-utc", required=True)
    review_label.add_argument("--evidence-ref", required=True)
    review_label.add_argument("--rationale", default="")
    review_label.add_argument(
        "--annotation-kind",
        choices=("independent", "adjudication"),
        default="independent",
    )
    review_label.add_argument("--supersedes", action="append")
    review_label.add_argument("--json", action="store_true")
    review_label.set_defaults(func=cmd_review_label)

    review_holdout = review_commands.add_parser(
        "holdout", help="report pinned exhibit labels on a frozen holdout partition"
    )
    review_holdout.add_argument("--run", required=True)
    review_holdout.add_argument("--spec", required=True)
    review_holdout.add_argument("--output")
    review_holdout.add_argument("--artifacts", default="")
    review_holdout.add_argument("--json", action="store_true")
    review_holdout.set_defaults(func=cmd_review_holdout)

    snapshot = commands.add_parser("snapshot", help="inspect S11 snapshot status")
    snapshot_commands = snapshot.add_subparsers(dest="snapshot_command", required=True)
    snapshot_status = snapshot_commands.add_parser(
        "status", help="show snapshot status"
    )
    snapshot_status.add_argument("--branch", default="main")
    _add_output_options(snapshot_status)
    snapshot_status.set_defaults(func=cmd_snapshot_status)
    snapshot_query = snapshot_commands.add_parser(
        "query", help="query snapshot relation"
    )
    snapshot_query.add_argument("--relation", required=True)
    snapshot_query.add_argument("--branch", default="main")
    snapshot_query.add_argument("--snapshot-id", default=None)
    snapshot_query.add_argument("--limit", type=positive_int_type, default=20)
    _add_output_options(snapshot_query)
    snapshot_query.set_defaults(func=cmd_snapshot_query)
    snapshot_list = snapshot_commands.add_parser(
        "list", help="list published snapshots"
    )
    _add_output_options(snapshot_list)
    snapshot_list.set_defaults(func=cmd_snapshot_list)

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
