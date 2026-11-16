"""Tests for the table_classification CLI surface."""

from __future__ import annotations

import json

from edgar_sec.pipelines.table_classification.cli import main


def test_cli_translate_json(capsys) -> None:  # noqa: ANN001
    assert main(["translate", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["triples"] == [
        {"role": "exhibit", "type": "EX-13", "optional": True}
    ]
    assert {row["family"] for row in payload["families"]} >= {"balance_sheet"}


def test_cli_plan_inspect_status_round_trip(tmp_path, capsys) -> None:  # noqa: ANN001
    plans = tmp_path / "table_classification" / "plans"
    code = main(
        [
            "plan",
            "--accession",
            "0000000001-26-000001",
            "--snapshot-id",
            "snap-1",
            "--stratum",
            "B",
            "--output",
            str(plans),
            "--json",
        ]
    )
    assert code == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["filings"] == 1
    assert planned["document_targets"] == 2
    # The plans-root override is the canonical plans root: the bundle
    # lands under its grandparent's table_classification/plans.
    assert planned["path"] == str(
        tmp_path / "table_classification" / "plans" / planned["plan_id"]
    )
    code = main(
        [
            "inspect",
            "--plan-id",
            planned["plan_id"],
            "--plans-root",
            str(plans),
            "--json",
        ]
    )
    assert code == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["source_snapshot_id"] == "snap-1"
    assert inspected["work_items"] == planned["work_items"]
    assert main(["status", "--plans-root", str(plans), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["plans"] == [planned["plan_id"]]
    assert status["store_published"] is False


def test_cli_run_with_unknown_plan_reports_the_missing_bundle(capsys) -> None:  # noqa: ANN001
    assert main(["run", "--plan-id", "any"]) == 1
    assert "no plan bundle" in capsys.readouterr().err
