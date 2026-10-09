"""Command surface for offline document target planning."""

from __future__ import annotations

import argparse
import sys

from .commands.inspect import cmd_inspect
from .commands.plan import cmd_plan
from .commands.status import cmd_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="planning",
        description="Plan document targets from published catalog and inventory artifacts",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    plan_parser = commands.add_parser(
        "plan", help="publish a deterministic target plan"
    )
    plan_parser.add_argument("--catalog-plan", required=True)
    plan_parser.add_argument("--inventory", default=None, help="snapshot id or current")
    profile_group = plan_parser.add_mutually_exclusive_group(required=True)
    profile_group.add_argument("--profile-id", help="profile ID to use")
    profile_group.add_argument(
        "--auto-primary-profile",
        action="store_true",
        help="generate or reuse the primary-only baseline profile",
    )
    plan_parser.add_argument("--artifacts", default="", help="artifacts root override")
    plan_parser.add_argument("--json", action="store_true")
    plan_parser.set_defaults(func=cmd_plan)

    inspect_parser = commands.add_parser("inspect", help="validate and inspect a plan")
    inspect_parser.add_argument("--plan-id", required=True)
    inspect_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.set_defaults(func=cmd_inspect)

    status_parser = commands.add_parser(
        "status", help="list profiles and published plans"
    )
    status_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    parsed = build_parser().parse_args(args)
    return int(parsed.func(parsed))


if __name__ == "__main__":
    sys.exit(main())
