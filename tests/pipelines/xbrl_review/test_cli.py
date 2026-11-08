"""Tests for XBRL review pipeline CLI dispatcher and commands."""

import json
from pathlib import Path

import pyarrow as pa
import pytest

from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.xbrl_review import cli as cli_module
from edgar_sec.pipelines.xbrl_review.cli import build_parser, main
from edgar_sec.pipelines.xbrl_review.execution import ExecutionResult
from edgar_sec.pipelines.xbrl_review.paths import HYPOTHESES_FILE
from edgar_sec.pipelines.xbrl_review.review import execute_review_generation
from edgar_sec.pipelines.xbrl_review.schemas import HYPOTHESES_SCHEMA


def test_build_parser_structure() -> None:
    """Verify parser includes project, execute, review, and dag subcommands."""
    parser = build_parser()
    choices = parser._subparsers._actions[1].choices
    assert "project" in choices
    assert "execute" in choices
    assert "review" in choices
    assert "fixture" not in choices
    assert "dag" in choices
    assert "benchmark" not in choices

    proj_opts = {
        opt for action in choices["project"]._actions for opt in action.option_strings
    }
    assert "--dataset" in proj_opts
    assert "--catalog-plan" not in proj_opts

    rev_p = choices["review"]
    assert "generate" in rev_p._subparsers._actions[1].choices
    assert "compare" in rev_p._subparsers._actions[1].choices
    assert "promote" in rev_p._subparsers._actions[1].choices
    assert "gates" in rev_p._subparsers._actions[1].choices


def _stub_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    result = ExecutionResult(
        run_id="run-42",
        snapshot_id="snap-abc123",
        chunks=5,
        filings=12,
        solved_count=90,
        quarantine_count=3,
        hypotheses_count=7,
        wall_ms=1234.0,
    )
    monkeypatch.setattr(
        cli_module,
        "execute_projection_run",
        lambda run_id, artifacts_root="": result,
    )


def test_cli_execute_text_renders_result_block(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Verify execute text mode renders as aligned key-values."""
    _stub_execution(monkeypatch)
    assert main(["execute", "--run-id", "run-42"]) == 0
    out = capsys.readouterr().out
    assert out == (
        "Executed run run-42\n"
        "  snapshot_id       snap-abc123\n"
        "  chunks            5\n"
        "  filings           12\n"
        "  solved_count      90\n"
        "  quarantine_count  3\n"
        "  hypotheses_count  7\n"
        "  wall_ms           1234.0 ms\n"
    )


def test_cli_execute_json_output_is_byte_exact(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Verify execute --json output keeps its exact serialized form."""
    _stub_execution(monkeypatch)
    assert main(["execute", "--run-id", "run-42", "--json"]) == 0
    out = capsys.readouterr().out
    assert out == (
        '{"chunks": 5, "filings": 12, "hypotheses_count": 7, '
        '"quarantine_count": 3, "run_id": "run-42", '
        '"snapshot_id": "snap-abc123", "solved_count": 90, '
        '"wall_ms": 1234.0}\n'
    )


def test_cli_promote_command(tmp_path: Path) -> None:
    """Verify promote command writes candidate rule to DuckDB database."""
    sample_filing = [
        {
            "ticker": "MSFT",
            "cik": 789019,
            "accession": "0000950170-24-087843",
            "fiscal_year": 2024,
            "period": "FY2024",
            "sector": "Technology",
            "facts": [
                {"concept": "us-gaap:GrossProfit", "value": 55.0, "unit": "USD"},
                {"concept": "msft:DirectRevenue", "value": 100.0, "unit": "USD"},
                {"concept": "msft:DirectCost", "value": 40.0, "unit": "USD"},
                {"concept": "msft:NovelCost", "value": 5.0, "unit": "USD"},
            ],
            "calc_arcs": [
                {
                    "parent": "us-gaap:GrossProfit",
                    "child": "msft:DirectRevenue",
                    "weight": 1.0,
                },
                {
                    "parent": "us-gaap:GrossProfit",
                    "child": "msft:DirectCost",
                    "weight": -1.0,
                },
            ],
            "targets": {"us-gaap:GrossProfit": 55.0},
        }
    ]
    run_dir = tmp_path / "test_run"
    execute_review_generation(sample_filing, run_id="test_run", output_root=tmp_path)

    hyp_p = run_dir / "cases" / "0000950170-24-087843" / HYPOTHESES_FILE
    assert hyp_p.is_file()
    write_parquet_table(
        pa.Table.from_pylist(
            [
                {
                    "rule_id": "HYP_RESIDUAL_0000950170-24-087843_0",
                    "hypothesis_type": "RESIDUAL_COMPONENT",
                    "target_concept": "us-gaap:GrossProfit",
                    "source_concept": "msft:NovelCost",
                    "algebraic_weight": 1.0,
                    "firm": "MSFT",
                    "sector": "Technology",
                    "evidence_value": 5.0,
                }
            ],
            schema=HYPOTHESES_SCHEMA,
        ),
        hyp_p,
    )

    evidence_path = tmp_path / "gate_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "census": {"passed": True},
                "pair_gate": {"passed": True, "total": 1},
                "battery": {
                    "total": 188,
                    "passed": 188,
                    "failures": [],
                },
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "promoted_rules.duckdb"
    exit_code = main(
        [
            "review",
            "promote",
            "--rule-id",
            "HYP_RESIDUAL_0000950170-24-087843_0",
            "--run-dir",
            str(run_dir),
            "--db-path",
            str(db_path),
            "--evidence",
            str(evidence_path),
        ]
    )
    assert exit_code == 0

    con = connect(database=db_path)
    res = con.execute(
        "SELECT rule_id, target_concept FROM xbrl_unification_rules"
    ).fetchall()
    con.close()
    assert len(res) == 1
    assert res[0][0] == "HYP_RESIDUAL_0000950170-24-087843_0"


def test_cli_project_dataset(tmp_path: Path) -> None:
    """Verify project command projects dataset into resumable work order."""
    dataset_file = tmp_path / "test_dataset.json"
    dataset_file.write_text(
        json.dumps(
            [
                {
                    "accession": "0000950170-24-000001",
                    "form": "10-K",
                    "filing_date": "2024-02-15",
                    "cik": 789019,
                    "period": "2023-12-31",
                }
            ]
        ),
        encoding="utf-8",
    )
    exit_code = main(
        [
            "project",
            "--dataset",
            str(dataset_file),
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )
    assert exit_code == 0
