from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.pipelines.document_inventory import cli
from edgar_sec.pipelines.document_inventory.fixture_store.capture import (
    create_index_fixture,
)
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    IndexCaptureFailure,
    IndexCaptureResult,
)
from edgar_sec.pipelines.document_inventory.paths import resolve_index_fixture_paths
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    FixtureContribution,
)


def _cohort() -> SimpleNamespace:
    return SimpleNamespace(
        work_items=(SimpleNamespace(accession="0000123456-12-000001"),)
    )


def _contribution() -> FixtureContribution:
    return FixtureContribution("p", "c", "10-K", "1", "f" * 64, 1)


def test_parser_exposes_fixture_and_review_commands() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        ["fixture", "create", "--fixture", "f", "--catalog-plan", "p", "--limit", "2"]
    )
    assert args.command == "fixture"
    assert args.fixture_command == "create"
    assert args.limit == 2
    assert (
        parser.parse_args(
            ["review-artifacts", "--fixture", "f", "--output", "review"]
        ).command
        == "review-artifacts"
    )


def test_fixture_commands_require_ids() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["fixture", "create", "--fixture", "f"])
    with pytest.raises(SystemExit):
        parser.parse_args(["fixture", "fill", "--catalog-plan", "p"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "fixture",
                "create",
                "--fixture",
                "f",
                "--catalog-plan",
                "p",
                "--limit",
                "0",
            ]
        )


def test_obsolete_placeholders_are_not_advertised() -> None:
    parser = cli.build_parser()
    for command in ("cohort", "index", "status", "query", "publish"):
        with pytest.raises(SystemExit):
            parser.parse_args([command])


def test_fixture_list_emits_manifest_discovery_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture_paths = resolve_index_fixture_paths(tmp_path, "f")
    create_index_fixture(fixture_paths, fixture_id="f")
    assert cli.main(["fixture", "list", "--artifacts", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["fixture_count"] == 1
    assert payload["fixtures"][0]["fixture_id"] == "f"


def test_create_uses_shared_capture_command_and_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    work = _cohort()
    plan = {"plan_id": "p", "catalog_id": "c", "scope": "10-K"}
    contribution_record = _contribution()
    broker = object()
    created: list[tuple[object, str]] = []
    captured: list[object] = []

    @contextmanager
    def managed(_socket: Path):
        yield broker

    monkeypatch.setattr(
        cli, "_cohort_for_plan", lambda *_args: (plan, work, contribution_record)
    )
    monkeypatch.setattr(cli, "managed_broker", managed)
    monkeypatch.setattr(
        cli,
        "create_index_fixture",
        lambda paths, fixture_id: created.append((paths, fixture_id)),
    )

    def capture(_cohort, *, fixture_id, paths, broker, contribution):
        captured.append((fixture_id, paths, broker, contribution))
        return IndexCaptureResult(1, 0, 1, 1, 1, ())

    monkeypatch.setattr(cli, "capture_index_pages", capture)
    code = cli.main(
        [
            "fixture",
            "create",
            "--fixture",
            "f",
            "--catalog-plan",
            "p",
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )
    assert code == 0
    assert created == [(resolve_index_fixture_paths(tmp_path, "f"), "f")]
    assert captured[0][2] is broker
    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_accessions"] == 1
    assert payload["responses_added"] == 1


def test_capture_failure_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    work = _cohort()
    failure = IndexCaptureFailure(
        AccessionNumber("0000123456-12-000001"), "http_error", "not found"
    )

    @contextmanager
    def managed(_socket: Path):
        yield object()

    monkeypatch.setattr(
        cli, "_cohort_for_plan", lambda *_args: ({}, work, _contribution())
    )
    monkeypatch.setattr(cli, "managed_broker", managed)
    monkeypatch.setattr(cli, "create_index_fixture", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cli,
        "capture_index_pages",
        lambda *_args, **_kwargs: IndexCaptureResult(0, 0, 1, 0, 1, (failure,)),
    )
    code = cli.main(
        [
            "fixture",
            "create",
            "--fixture",
            "f",
            "--catalog-plan",
            "p",
            "--artifacts",
            str(tmp_path),
        ]
    )
    assert code == 1
    assert "http_error" in capsys.readouterr().err


def test_cli_interrupt_maps_to_130(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_fixture_list", interrupted)
    assert cli.main(["fixture", "list"]) == 130


def test_no_args_prints_help_instead_of_json_prompt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["inventory"])
    assert cli.main(None) == 0
    assert "fixture" in capsys.readouterr().out


def test_cli_dispatches_dag_subcommand(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["dag", "--root", str(tmp_path), "status"]) == 1
    assert "No active snapshot pointer" in capsys.readouterr().out
