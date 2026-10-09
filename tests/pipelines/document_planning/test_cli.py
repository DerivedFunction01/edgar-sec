from __future__ import annotations

from edgar_sec.pipelines.document_planning import cli


def test_cli_parses_plan_inspect_and_status() -> None:
    plan = cli.build_parser().parse_args(
        ["plan", "--catalog-plan", "cat-1", "--profile-id", "primary"]
    )
    inspect = cli.build_parser().parse_args(["inspect", "--plan-id", "dplan-1"])
    status = cli.build_parser().parse_args(["status", "--json"])

    assert plan.command == "plan"
    assert plan.inventory is None
    assert inspect.plan_id == "dplan-1"
    assert status.json


def test_cli_dispatches_parsed_subcommand(monkeypatch) -> None:
    monkeypatch.setattr(cli, "cmd_status", lambda _args: 7)

    assert cli.main(["status", "--json"]) == 7
