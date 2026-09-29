"""Command surface, settings resolution, and launcher registration tests.

The settings test is the load-bearing one. ``runtime.chunk_size`` and
``runtime.partition_count`` are registered specs with env names, and for a long
period nothing read them: the parser hardcoded the module constants, so
``RUNTIME_CHUNK_SIZE=2`` still produced a plan claiming 1000. Because the plan id
is derived from the effective chunking, that plan then became the canonical
record of a run the operator never asked for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.foundation.runtime.settings.runtime import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_PARTITION_COUNT,
)
from edgar_sec.pipelines.metadata_sync import cli as cli_module
from edgar_sec.pipelines.metadata_sync.cli import (
    RunOptions,
    _options,
    build_parser,
    main,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_NAME,
    SOURCE_URL,
    refresh_company_tickers,
)
from edgar_sec.pipelines.metadata_sync.worker import resolve_workers
from tests.support import FakeSession, build_test_http, fixture_path

COMMANDS = ("plan", "status", "run", "merge", "augment", "sources")

SOURCE_TICKERS = {
    "0": {"cik_str": "37996", "ticker": "F", "title": "FORD MOTOR CO"},
    "1": {"cik_str": "20", "ticker": "KTC", "title": "K Tron International Inc"},
    "2": {"cik_str": "5555", "ticker": "NEW", "title": "NEWCO INC"},
}


def _seed_session(session: FakeSession) -> None:
    """Register one submissions payload per CIK in the committed mini manifest."""
    for cik in ("0000001985", "0000001761", "0000000020", "0000037996"):
        session.register(
            submissions_url(cik),
            {
                "name": f"COMPANY {cik}",
                "filings": {
                    "recent": {
                        "accessionNumber": [f"{cik}-26-000001"],
                        "filingDate": ["2026-01-02"],
                        "form": ["10-K"],
                        "size": [1024],
                    },
                    "files": [],
                },
            },
        )


def _subparser(command: str):
    parser = build_parser()
    action = next(
        act
        for act in parser._actions
        if getattr(act, "choices", None) and command in (act.choices or {})
    )
    return action.choices[command]


def test_parser_registers_the_documented_commands() -> None:
    parser = build_parser()
    registered = next(
        act.choices for act in parser._actions if getattr(act, "choices", None)
    )
    assert set(registered) == set(COMMANDS)


def test_sources_registers_refresh_and_compare() -> None:
    sources = _subparser("sources")
    nested = next(
        act.choices for act in sources._actions if getattr(act, "choices", None)
    )
    assert set(nested) == {"refresh", "compare"}


def test_every_command_requires_an_input() -> None:
    for command in ("plan", "status", "run", "merge", "augment"):
        flags = {
            option
            for action in _subparser(command)._actions
            for option in action.option_strings
        }
        assert "--input" in flags, command


def test_merge_rejects_a_snapshot_id_override() -> None:
    """Snapshot identity is plan-derived, so a rename flag cannot be accepted.

    Accepting ``--snapshot-id`` here would publish an artifact whose rows still
    carry the plan id, so the flag is removed rather than wired to a late rename.
    """
    flags = {
        option
        for action in _subparser("merge")._actions
        for option in action.option_strings
    }
    assert "--snapshot-id" not in flags
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["merge", "--input", "x.csv", "--snapshot-id", "renamed"]
        )


def test_parser_defaults_do_not_read_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building a parser must stay pure; resolution belongs to the options boundary."""
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    args = build_parser().parse_args(["plan", "--input", "x.csv"])
    assert args.chunk_size is None
    assert args.partition_count is None


def test_options_fall_back_to_the_settings_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    monkeypatch.setenv("RUNTIME_PARTITION_COUNT", "3")
    args = build_parser().parse_args(["plan", "--input", "x.csv"])
    options = _options(args)
    assert options.chunk_size == 7
    assert options.partition_count == 3


def test_explicit_flags_override_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    args = build_parser().parse_args(["plan", "--input", "x.csv", "--chunk-size", "5"])
    assert _options(args).chunk_size == 5


def test_options_default_to_the_code_defaults() -> None:
    args = build_parser().parse_args(["plan", "--input", "x.csv"])
    options = _options(args)
    assert options.chunk_size == DEFAULT_CHUNK_SIZE
    assert options.partition_count == DEFAULT_PARTITION_COUNT
    assert options.workers is None


def test_plan_command_honors_environment_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The regression itself: the written plan must record the declared settings."""
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "2")
    monkeypatch.setenv("RUNTIME_PARTITION_COUNT", "3")
    exit_code = main(
        [
            "plan",
            "--input",
            str(fixture_path("cik_sec_mini.csv")),
            "--artifacts",
            str(tmp_path),
        ]
    )
    assert exit_code == 0

    plans = list(tmp_path.rglob("plan.json"))
    assert len(plans) == 1
    plan = json.loads(plans[0].read_text(encoding="utf-8"))
    assert plan["chunk_size"] == 2
    assert plan["partition_count"] == 3
    assert len(plan["chunks"]) == 2
    assert "written" in capsys.readouterr().out


def test_plan_command_limit_truncates_both_ciks_and_names(tmp_path: Path) -> None:
    assert (
        main(
            [
                "plan",
                "--input",
                str(fixture_path("cik_sec_mini.csv")),
                "--artifacts",
                str(tmp_path),
                "--limit",
                "2",
                "--chunk-size",
                "10",
            ]
        )
        == 0
    )
    plan = json.loads(next(tmp_path.rglob("plan.json")).read_text(encoding="utf-8"))
    assert plan["row_count"] == 2


def test_status_reports_progress_offline(tmp_path: Path, capsys) -> None:
    manifest = str(fixture_path("cik_sec_mini.csv"))
    assert (
        main(
            [
                "plan",
                "--input",
                manifest,
                "--artifacts",
                str(tmp_path),
                "--chunk-size",
                "2",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "status",
                "--input",
                manifest,
                "--artifacts",
                str(tmp_path),
                "--chunk-size",
                "2",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["planned_chunks"] == 2
    assert payload["completed_chunks"] == 0
    assert payload["mergeable"] is False
    assert payload["schema_version"]


def test_changed_effective_chunking_fails_loudly(tmp_path: Path, capsys) -> None:
    """No persisted config means the plan id follows the effective settings.

    Planning with ``--chunk-size 2`` and then running without it resolves a
    different plan, so the command must refuse rather than quietly reuse the
    checkpoints of a differently-chunked plan.
    """
    manifest = str(fixture_path("cik_sec_mini.csv"))
    assert (
        main(
            [
                "plan",
                "--input",
                manifest,
                "--artifacts",
                str(tmp_path),
                "--chunk-size",
                "2",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["status", "--input", manifest, "--artifacts", str(tmp_path)]) == 1
    assert "missing plan" in capsys.readouterr().err


def test_missing_plan_reports_an_error(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "status",
            "--input",
            str(fixture_path("cik_sec_mini.csv")),
            "--artifacts",
            str(tmp_path),
        ]
    )
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def test_run_rejects_an_unknown_partition(
    tmp_path: Path, client: SubmissionsClient, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli_module, "_build_client", lambda: client)
    manifest = str(fixture_path("cik_sec_mini.csv"))
    assert main(["plan", "--input", manifest, "--artifacts", str(tmp_path)]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "run",
                "--input",
                manifest,
                "--artifacts",
                str(tmp_path),
                "--partition",
                "7",
            ]
        )
        == 1
    )
    assert "partition 7 is not present" in capsys.readouterr().err


def test_run_partition_executes_and_then_skips_completed_chunks(
    tmp_path: Path, client: SubmissionsClient, session: FakeSession, monkeypatch, capsys
) -> None:
    """``--partition`` is a real execution unit, not a chunk-id filter.

    The partition branch routes through ``worker.run_partition``; running it twice
    must not refetch, which is only observable if the second pass takes the
    already-complete path for every chunk in the partition.
    """
    _seed_session(session)

    monkeypatch.setattr(cli_module, "_build_client", lambda: client)
    manifest = str(fixture_path("cik_sec_mini.csv"))
    plan_argv = [
        "--input",
        manifest,
        "--artifacts",
        str(tmp_path),
        "--chunk-size",
        "2",
        "--partition-count",
        "2",
    ]
    assert main(["plan", *plan_argv]) == 0
    capsys.readouterr()

    run_argv = ["run", *plan_argv, "--partition", "0"]
    assert main(run_argv) == 0
    assert "chunk 0:" in capsys.readouterr().out
    calls_after_first = len(session.calls)

    assert main(run_argv) == 0
    assert "already complete, skipped" in capsys.readouterr().out
    assert len(session.calls) == calls_after_first


def test_main_dispatches_to_the_selected_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["plan", "--input", "x.csv"])
    assert args.func.__name__ == "cmd_plan"
    assert parser.parse_args(["merge", "--input", "x.csv"]).func.__name__ == "cmd_merge"


def test_sources_compare_requires_its_arguments() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["sources", "compare", "--input", "x.csv"])


def test_sources_refresh_routes_the_artifacts_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sources refresh` must reach the library, not just parse its arguments."""
    captured: dict[str, object] = {}

    def fake_refresh(*, metadata_paths, client=None):
        captured["artifacts_root"] = metadata_paths.artifacts_root
        return {
            "source": "company_tickers",
            "snapshot_id": "snap1",
            "validation_status": "ok",
        }

    monkeypatch.setattr(cli_module, "refresh_company_tickers", fake_refresh)
    assert main(["sources", "refresh", "--artifacts", str(tmp_path)]) == 0
    assert captured["artifacts_root"] == tmp_path.resolve()


def test_sources_refresh_reports_a_failure_as_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def explode(**_kwargs):
        raise ValueError("source unavailable")

    monkeypatch.setattr(cli_module, "refresh_company_tickers", explode)
    assert main(["sources", "refresh", "--artifacts", str(tmp_path)]) == 1
    assert "error: source unavailable" in capsys.readouterr().err


def test_sources_compare_publishes_artifacts_through_the_cli(
    session: FakeSession, tmp_path: Path, capsys
) -> None:
    """End to end through `main`, asserting the artifacts the command claims."""
    session.register_bytes(SOURCE_URL, json.dumps(SOURCE_TICKERS).encode("utf-8"))
    metadata = resolve_metadata_paths(tmp_path)
    published = refresh_company_tickers(
        metadata_paths=metadata, client=build_test_http(session)
    )
    manifest_path = metadata.source_manifest_file(SOURCE_NAME, published["snapshot_id"])
    capsys.readouterr()

    exit_code = main(
        [
            "sources",
            "compare",
            "--input",
            str(fixture_path("cik_sec_mini.csv")),
            "--source-manifest",
            str(manifest_path),
            "--artifacts",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["source"] == SOURCE_NAME
    assert summary["new_cik_count"] == 1

    registry_id = summary["registry_id"]
    for dataset in (
        "listing_observations",
        "registrant_registry",
        "new_ciks",
        "augmentation_worklist",
    ):
        assert metadata.registry_dataset(registry_id, dataset).is_file()
    assert metadata.effective_input_file(registry_id).is_file()


def test_sources_compare_reports_a_bad_manifest_as_exit_1(
    tmp_path: Path, capsys
) -> None:
    exit_code = main(
        [
            "sources",
            "compare",
            "--input",
            str(fixture_path("cik_sec_mini.csv")),
            "--source-manifest",
            str(tmp_path / "absent.json"),
            "--artifacts",
            str(tmp_path),
        ]
    )
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def test_worker_count_stays_machine_derived_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--workers` unset must keep deriving from cgroups, not degrade to zero.

    `runtime.workers` has a callable default, so an explicit `0` would have meant
    "zero workers" rather than "derive it". That distinction is why the flag
    defaults to unset rather than to 0, and the registry must still be honoured.
    """
    monkeypatch.setenv("RUNTIME_WORKERS", "3")
    args = build_parser().parse_args(["run", "--input", "x.csv"])
    assert _options(args).workers is None
    assert resolve_workers(_options(args).workers) == 3

    monkeypatch.delenv("RUNTIME_WORKERS")
    assert resolve_workers(None) >= 1


def test_run_options_derive_the_plan_id_from_effective_chunking() -> None:
    options = RunOptions(input_path=Path("x.csv"), chunk_size=5, partition_count=2)
    assert options.effective_plan_id("fp") == options.effective_plan_id("fp")
    assert options.effective_plan_id("other") != options.effective_plan_id("fp")
    fixed = RunOptions(input_path=Path("x.csv"), plan_id="fixed")
    assert fixed.effective_plan_id("fp") == "fixed"


def test_metadata_is_registered_in_the_launcher() -> None:
    import run as launcher

    entry = next(item for item in launcher.ENTRIES if item.id == "metadata")
    assert entry.module == "edgar_sec.pipelines.metadata_sync.operator"
