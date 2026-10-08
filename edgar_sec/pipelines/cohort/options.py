"""Argument parsing helpers for the cohort command surface."""

from __future__ import annotations

import argparse


def csv_values(value: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in value.split(",") if part.strip())
    if not values:
        raise argparse.ArgumentTypeError("provide at least one comma-separated value")
    return values


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgar-sec cohort",
        description=(
            "Import, inspect, query, and combine registrant cohorts. Membership is "
            "deduplicated by CIK. File duplicates use the first non-empty trimmed "
            "input-row name. Union/intersection prefer the left operand's non-empty "
            "name, then the right; put official SEC sources on the left to prioritize "
            "their labels. Blank names fall through without creating duplicate members."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    intake = commands.add_parser(
        "import", help="import a delimited, text, or Parquet file"
    )
    intake.add_argument("--input", required=True)
    intake.add_argument("--name")
    intake.add_argument("--tags", type=csv_values, default=())
    intake.add_argument("--delimiter", choices=(",", "\t", r"\t", "|"))
    intake.add_argument("--limit", type=positive_int)

    listing = commands.add_parser("list", help="list catalog cohorts")
    listing.add_argument("--tag")
    listing.add_argument("--pinned-only", action="store_true")
    listing.add_argument("--search")
    listing.add_argument("--limit", type=positive_int, default=50)
    listing.add_argument("--offset", type=non_negative_int, default=0)

    info = commands.add_parser("info", help="show cohort metadata and sample members")
    info.add_argument("cohort")

    rename = commands.add_parser("rename", help="rename a cohort")
    rename.add_argument("cohort")
    rename.add_argument("--name", required=True)

    tag = commands.add_parser("tag", help="add or remove cohort tags")
    tag.add_argument("cohort")
    tag.add_argument("--add", type=csv_values, default=())
    tag.add_argument("--remove", type=csv_values, default=())

    untag = commands.add_parser("untag", help="remove cohort tags")
    untag.add_argument("cohort")
    untag.add_argument(
        "--tags", "--remove", dest="remove", required=True, type=csv_values
    )

    delete = commands.add_parser("delete", help="delete a cohort")
    delete.add_argument("cohort")
    delete.add_argument("--keep-dataset", action="store_true")

    query = commands.add_parser("query", help="query members of one cohort")
    query.add_argument("cohort")
    query.add_argument("--cik")
    query.add_argument("--name")
    query.add_argument("--limit", type=positive_int, default=25)
    query.add_argument("--offset", type=non_negative_int, default=0)

    find = commands.add_parser("find", help="search members across cohorts")
    find.add_argument("--cik")
    find.add_argument("--name")
    find.add_argument("--limit", type=positive_int, default=25)
    find.add_argument("--page", type=positive_int, default=1)

    sample = commands.add_parser("sample", help="create a deterministic cohort sample")
    sample.add_argument("--source", required=True)
    sample.add_argument("--method", choices=("modulo", "random"), default="modulo")
    sample.add_argument("--rate", type=float)
    sample.add_argument("--limit", type=positive_int)
    sample.add_argument("--seed", type=int, default=42)
    sample.add_argument("--group-family", action="store_true")
    sample.add_argument("--family-index")
    sample.add_argument("--exclude-spv", action="store_true")
    sample.add_argument("--name")

    sources = commands.add_parser("sources", help="manage official SEC source cohorts")
    source_commands = sources.add_subparsers(dest="sources_command", required=True)
    refresh = source_commands.add_parser(
        "refresh", help="refresh an official SEC source cohort"
    )
    refresh.add_argument(
        "--source",
        choices=("cik_lookup", "company_tickers"),
        default="cik_lookup",
        help="which official source to refresh",
    )

    diff = commands.add_parser("diff", help="compare cohort membership")
    diff.add_argument("left")
    diff.add_argument("right")
    diff.add_argument("--save-left-delta", metavar="NAME")
    diff.add_argument("--save-right-delta", metavar="NAME")

    commands.add_parser("family-index", help="publish the active universe family index")

    workspace = commands.add_parser(
        "workspace", help="manage workspace sessions and variables"
    )
    workspace_commands = workspace.add_subparsers(
        dest="workspace_command", required=True
    )
    init = workspace_commands.add_parser("init", help="create and activate a session")
    init.add_argument("session_id")
    use = workspace_commands.add_parser("use", help="activate a session")
    use.add_argument("session_id")
    workspace_commands.add_parser("current", help="show the active session")
    workspace_commands.add_parser("sessions", help="list workspace sessions")
    for name in (
        "bind",
        "let",
        "diff",
        "peek",
        "save",
        "list",
        "drop",
        "clear",
        "clean",
    ):
        child = workspace_commands.add_parser(name)
        child.add_argument("--session")
    workspace_commands.choices["bind"].add_argument("alias")
    workspace_commands.choices["bind"].add_argument("cohort")
    workspace_commands.choices["let"].add_argument("variable")
    workspace_commands.choices["let"].add_argument("expression")
    workspace_commands.choices["diff"].add_argument("left")
    workspace_commands.choices["diff"].add_argument("right")
    workspace_commands.choices["peek"].add_argument("variable")
    workspace_commands.choices["peek"].add_argument(
        "--limit", type=positive_int, default=10
    )
    workspace_commands.choices["save"].add_argument("variable")
    workspace_commands.choices["save"].add_argument("--name", required=True)
    workspace_commands.choices["save"].add_argument(
        "--tags", type=csv_values, default=()
    )
    workspace_commands.choices["drop"].add_argument("variable")
    workspace_commands.choices["clean"].add_argument("--older-than", default="24h")

    merge = commands.add_parser("merge", help="evaluate a cohort set expression")
    merge.add_argument("--expr", required=True)
    merge.add_argument("--name")
    merge.add_argument("--tags", type=csv_values, default=())
    merge.add_argument("--serialize", action="store_true")

    commands.add_parser("console", help="open the interactive cohort console")
    return parser


__all__ = ["build_parser", "csv_values", "non_negative_int", "positive_int"]
