"""Unit tests for XBRL CLI dispatcher and commands."""

from pathlib import Path
from edgar_sec.engine.xbrl.review.cli import build_parser, main
from edgar_sec.engine.xbrl.review.review import execute_review_generation
from edgar_sec.infra.storage.duckdb import connect


def test_build_parser_structure() -> None:
    """Verify parser includes review subcommands and options."""
    parser = build_parser()
    assert "review" in parser._subparsers._actions[1].choices
    assert "benchmark" in parser._subparsers._actions[1].choices

    rev_p = parser._subparsers._actions[1].choices["review"]
    assert "generate" in rev_p._subparsers._actions[1].choices
    assert "compare" in rev_p._subparsers._actions[1].choices
    assert "promote" in rev_p._subparsers._actions[1].choices


def test_cli_promote_command(tmp_path: Path) -> None:
    """Verify promote command writes candidate rule to target DuckDB database."""
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

    hyp_p = run_dir / "cases" / "0000950170-24-087843" / "hypotheses.json"
    assert hyp_p.is_file()

    db_path = tmp_path / "promoted_rules.duckdb"
    exit_code = main(
        [
            "review",
            "promote",
            "--rule-id",
            "HYP_SHADOW_0000950170-24-087843_0",
            "--run-dir",
            str(run_dir),
            "--db-path",
            str(db_path),
        ]
    )
    assert exit_code == 0

    con = connect(database=db_path)
    res = con.execute(
        "SELECT rule_id, target_concept FROM xbrl_unification_rules"
    ).fetchall()
    con.close()
    assert len(res) == 1
    assert res[0][0] == "HYP_SHADOW_0000950170-24-087843_0"
