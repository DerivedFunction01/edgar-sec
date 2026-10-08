"""Unit tests for the filing-catalog command surface."""

from __future__ import annotations

import json
from pathlib import Path

from typing import Any

import pytest

from edgar_sec.pipelines.filing_catalog.cli import (
    build_parser,
    cmd_expand,
    main,
)
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths

SAMPLE = "tests/fixtures/catalog/sample_submission_metadata.parquet"


def _json_output(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    out = capsys.readouterr().out
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        pass
    result: dict[str, Any] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            key, val = parts
            if val.isdigit():
                result[key] = int(val)
            elif val == "none":
                result[key] = None
            else:
                result[key] = val
    return result


# --- parser ---------------------------------------------------------------


def test_parser_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_parser_exposes_expected_commands() -> None:
    parser = build_parser()
    actions = [
        action
        for action in parser._actions
        if getattr(action, "choices", None) and "status" in (action.choices or {})
    ]
    assert actions
    assert set(actions[0].choices) == {"materialize", "plan", "expand", "status", "dag"}


def test_plan_accepts_repeated_form_and_suffix_flags() -> None:
    args = build_parser().parse_args(
        ["plan", "--catalog", "abc", "--forms", "10-K", "10-Q", "--suffixes", ".htm"]
    )
    assert args.forms == ["10-K", "10-Q"]
    assert args.suffixes == [".htm"]


def test_plan_requires_a_catalog() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["plan"])


def test_no_per_keyword_date_flag_exists_on_plan() -> None:
    """Silently ignoring `--start-date` would publish a plan over every date."""
    for flag in ("--start-date", "--end-date", "--filing-date", "--era", "--years"):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["plan", "--catalog", "abc", flag, "2020-01-01"])


def test_plan_defaults_to_no_date_selection() -> None:
    args = build_parser().parse_args(["plan", "--catalog", "abc"])
    assert args.dates == ""


def test_plan_takes_the_date_selection_as_one_quoted_value() -> None:
    """One value, not ``nargs="*"``: a comma separates clauses, not arguments."""
    args = build_parser().parse_args(
        [
            "plan",
            "--catalog",
            "abc",
            "--dates",
            "@Q1[1999..2001],2005Q3..2008Q1,2011-12-31..2019-11-03",
        ]
    )
    assert args.dates == "@Q1[1999..2001],2005Q3..2008Q1,2011-12-31..2019-11-03"


def test_plan_does_not_split_the_date_selection_into_a_list() -> None:
    args = build_parser().parse_args(
        ["plan", "--catalog", "abc", "--dates", "2023,2024"]
    )
    assert args.dates == "2023,2024"


def test_an_invalid_date_selection_is_reported_not_published(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts = tmp_path / "art"
    main(["materialize", "--source", SAMPLE, "--artifacts", str(artifacts)])
    catalog_id = _json_output(capsys)["catalog_id"]
    code = main(
        [
            "plan",
            "--catalog",
            catalog_id,
            "--artifacts",
            str(artifacts),
            "--dates",
            "2024Q5",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "2024Q5" in captured.err
    assert captured.out == ""


def test_plan_publishes_the_requested_date_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts = tmp_path / "art"
    main(["materialize", "--source", SAMPLE, "--artifacts", str(artifacts)])
    catalog_id = _json_output(capsys)["catalog_id"]
    assert (
        main(
            [
                "plan",
                "--catalog",
                catalog_id,
                "--artifacts",
                str(artifacts),
                "--dates",
                "2024",
            ]
        )
        == 0
    )
    out_plan = _json_output(capsys)
    assert out_plan["selected_rows"] == 1
    plan_file = (
        resolve_filing_catalog_paths(artifacts).plan_dir(out_plan["plan_id"])
        / "plan.json"
    )
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    assert plan["date_selection"] == [
        {"kind": "absolute", "start_date": "2024-01-01", "end_date": "2024-12-31"}
    ]
    assert plan["selected_rows"] == 1


# --- commands -------------------------------------------------------------


def test_materialize_then_plan_then_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts = tmp_path / "art"

    assert main(["materialize", "--source", SAMPLE, "--artifacts", str(artifacts)]) == 0
    manifest = _json_output(capsys)
    catalog_id = manifest["catalog_id"]
    assert manifest["target_row_count"] == 13

    assert (
        main(
            [
                "plan",
                "--catalog",
                catalog_id,
                "--artifacts",
                str(artifacts),
                "--forms",
                "10-K",
            ]
        )
        == 0
    )
    plan = _json_output(capsys)
    assert plan["selected_rows"] == 4

    assert main(["status", "--artifacts", str(artifacts)]) == 0
    summary = _json_output(capsys)
    assert summary["catalog_count"] == 1
    assert summary["plan_count"] == 1
    assert summary["current_catalog_id"] is None  # non-durable run


def test_status_on_an_empty_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", "--artifacts", str(tmp_path / "empty")]) == 0
    summary = _json_output(capsys)
    assert summary["catalog_count"] == 0


def test_materialize_reports_a_transient_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chunk = tmp_path / "chunks" / "chunk_0000.parquet"
    chunk.parent.mkdir(parents=True)
    chunk.write_bytes(b"x")
    assert main(["materialize", "--source", str(chunk)]) == 1
    assert "finalized artifact" in capsys.readouterr().err


def test_materialize_without_a_source_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path / "empty"))
    assert main(["materialize"]) == 1
    assert "no Phase 1 snapshot" in capsys.readouterr().err


def test_plan_reports_an_unpublished_catalog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["plan", "--catalog", "missing", "--artifacts", str(tmp_path)]) == 1
    assert "no published targets" in capsys.readouterr().err


def test_plan_current_alias_resolves_via_the_pointer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path / "durable"))
    assert main(["materialize", "--source", SAMPLE]) == 0
    capsys.readouterr()
    assert main(["plan", "--catalog", "current", "--forms", "10-K"]) == 0
    plan_summary = _json_output(capsys)
    assert plan_summary["selected_rows"] == 4
    plan_file = (
        resolve_filing_catalog_paths(tmp_path / "durable").plan_dir(
            plan_summary["plan_id"]
        )
        / "plan.json"
    )
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    assert plan["selected_rows"] == 4
    assert plan["forms"] == ["10-K"]


def test_plan_current_without_a_pointer_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["plan", "--catalog", "current", "--artifacts", str(tmp_path)]) == 1
    assert "no catalog is published as current" in capsys.readouterr().err


# --- launcher registry -----------------------------------------------------


def test_cli_main_is_reachable_through_the_launcher_registry() -> None:
    import run

    ids = {entry.id for entry in run.ENTRIES}
    assert "filing-catalog" in ids
    entry = next(e for e in run.ENTRIES if e.id == "filing-catalog")
    assert entry.module == "edgar_sec.pipelines.filing_catalog.operator"


def test_plan_defaults_to_the_deterministic_scope() -> None:
    args = build_parser().parse_args(["plan", "--catalog", "abc"])
    assert args.scope == "deterministic"
    assert args.policy == ""
    assert args.auto_policy is False


def test_plan_accepts_the_policy_scope_with_a_policy_document() -> None:
    args = build_parser().parse_args(
        ["plan", "--catalog", "abc", "--scope", "policy", "--policy", "p.json"]
    )
    assert args.scope == "policy"
    assert args.policy == "p.json"


def test_plan_accepts_the_policy_scope_with_auto_generation() -> None:
    args = build_parser().parse_args(
        ["plan", "--catalog", "abc", "--scope", "policy", "--auto-policy"]
    )
    assert args.auto_policy is True


def test_plan_rejects_an_unknown_scope() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["plan", "--catalog", "abc", "--scope", "guess"])


def test_policy_scope_requires_a_policy_source() -> None:
    """Silently assuming a quota profile would be indistinguishable from a chosen one."""
    from edgar_sec.pipelines.filing_catalog.cli import cmd_plan

    args = build_parser().parse_args(["plan", "--catalog", "abc", "--scope", "policy"])
    assert cmd_plan(args) == 1


def test_policy_scope_rejects_two_policy_sources() -> None:
    from edgar_sec.pipelines.filing_catalog.cli import cmd_plan

    args = build_parser().parse_args(
        [
            "plan",
            "--catalog",
            "abc",
            "--scope",
            "policy",
            "--policy",
            "p.json",
            "--auto-policy",
        ]
    )
    assert cmd_plan(args) == 1


def test_expand_requires_a_parent_and_a_target() -> None:
    args = build_parser().parse_args(
        ["expand", "--parent-plan", "/tmp/p", "--target-units", "10"]
    )
    assert args.parent_plan == "/tmp/p"
    assert args.target_units == 10


def test_expand_reports_a_missing_parent_cleanly(tmp_path, capsys) -> None:
    assert (
        cmd_expand(
            build_parser().parse_args(
                [
                    "expand",
                    "--parent-plan",
                    str(tmp_path / "absent"),
                    "--target-units",
                    "5",
                ]
            )
        )
        == 1
    )
    assert "error:" in capsys.readouterr().err
