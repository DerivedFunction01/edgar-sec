"""Command surface, settings resolution, and launcher registration; a setting the
parser ignores would still reach the plan id.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from typing import Any

from edgar_sec.domain.sec_urls import submissions_url
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.pipelines.metadata_sync import cli as cli_module
from edgar_sec.pipelines.metadata_sync.cli import build_parser, main
from edgar_sec.pipelines.metadata_sync.options import (
    plan_options,
    read_bundle_plan_id,
    resolve_chunk_size,
    run_options,
)
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from edgar_sec.pipelines.metadata_sync.worker import resolve_workers
from tests.pipelines.metadata_sync.cohort_support import publish_test_cohort
from tests.support import (
    FakeSession,
    build_test_http,
    cik_payload,
    fixture_path,
)

COMMANDS = (
    "plan",
    "status",
    "run",
    "merge",
    "distrib",
    "augment",
    "dag",
)

MINI = ["0000001985", "0000001761", "0000000020", "0000037996"]


def _seed_session(session: FakeSession) -> None:
    for cik in MINI:
        session.register(submissions_url(cik), cik_payload(cik, f"COMPANY {cik}"))


def _parse_output(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    out = capsys.readouterr().out
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        pass
    result: dict[str, Any] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or "  " not in line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            key, val = parts
            if val.isdigit():
                result[key] = int(val)
            elif val == "True":
                result[key] = True
            elif val == "False":
                result[key] = False
            elif val == "none":
                result[key] = None
            else:
                result[key] = val
    return result


def _subparser(command: str):
    parser = build_parser()
    action = next(
        act
        for act in parser._actions
        if getattr(act, "choices", None) and command in (act.choices or {})
    )
    return action.choices[command]


def _flags(command: str) -> set[str]:
    return {
        option
        for action in _subparser(command)._actions
        for option in action.option_strings
    }


def _cohort_id(artifacts: Path) -> str:
    record, _paths, _roster = publish_test_cohort(
        fixture_path("cik_sec_mini.csv"), artifacts
    )
    return record.cohort_id


def _plan_argv(artifacts: Path, *extra: str) -> list[str]:
    return [
        "plan",
        "--cohort",
        _cohort_id(artifacts),
        "--artifacts",
        str(artifacts),
        *extra,
    ]


# ------------------------------------------------------------------ the surface


def test_parser_registers_the_documented_commands() -> None:
    parser = build_parser()
    registered = next(
        act.choices for act in parser._actions if getattr(act, "choices", None)
    )
    assert set(registered) == set(COMMANDS)


def test_source_management_is_not_in_the_metadata_command_surface() -> None:
    parser = build_parser()
    commands = next(action.choices for action in parser._actions if action.choices)
    assert not {"sources", "cohort", "family-index"} & commands.keys()
    with pytest.raises(SystemExit):
        parser.parse_args(["sources", "refresh"])


def test_distrib_registers_distribution_subcommands() -> None:
    distrib = _subparser("distrib")
    nested = next(
        act.choices for act in distrib._actions if getattr(act, "choices", None)
    )
    assert set(nested) == {"export", "worker", "import", "list", "commands"}


def test_a_plan_needs_a_cohort_reference() -> None:
    for command in ("plan", "augment"):
        flags = _flags(command)
        assert "--cohort" in flags
        assert not {"--input", "--roster", "--universe"} & flags


def test_a_plan_with_no_cohort_reference_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["plan"])


def test_execution_commands_accept_a_plan_reference() -> None:
    for command in ("status", "run", "merge"):
        flags = _flags(command)
        assert {"--plan-id", "--bundle", "--cohort"} <= flags
        assert not {"--input", "--roster", "--universe"} & flags


def test_augment_needs_a_base_but_not_a_hand_typed_snapshot_id() -> None:
    """Requiring it forced an operator to invent an id on every surface."""
    assert "--base-snapshot-id" in _flags("augment")
    assert "--new-snapshot-id" in _flags("augment")
    args = build_parser().parse_args(
        [
            "augment",
            "--cohort",
            "c-test",
            "--base-snapshot-id",
            "base",
            "--new-snapshot-id",
            "next",
            "--chunk-size",
            "5",
            "--workers",
            "2",
        ]
    )
    assert (args.cohort, args.base_snapshot_id, args.new_snapshot_id) == (
        "c-test",
        "base",
        "next",
    )
    assert args.chunk_size == 5
    assert args.workers == 2

    parsed = build_parser().parse_args(
        [
            "augment",
            "--cohort",
            "cohort-1",
            "--base-snapshot-id",
            "base",
        ]
    )
    assert parsed.new_snapshot_id == ""


def test_augment_still_refuses_to_run_without_a_base() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["augment", "--cohort", "cohort-1"])


def test_merge_rejects_a_snapshot_id_override() -> None:
    """Rows keep the plan id, so a late rename could not be honoured."""
    assert "--snapshot-id" not in _flags("merge")
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["merge", "--plan-id", "p", "--snapshot-id", "renamed"]
        )


def test_no_command_exposes_a_partition_count() -> None:
    """Assignment carries the split, so worker config cannot move the plan directory."""
    for command in ("plan", "status", "run", "merge", "augment"):
        assert "--partition-count" not in _flags(command), command


# ------------------------------------------------------------------- settings


def test_parser_defaults_do_not_read_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building a parser must stay pure; resolution belongs to the options boundary."""
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    args = build_parser().parse_args(["plan", "--cohort", "c-test"])
    assert args.chunk_size is None


def test_options_fall_back_to_the_settings_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    options = plan_options(cohort="c-test")
    assert options.chunk_size == 7


def test_explicit_flags_override_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    assert plan_options(cohort="c-test", chunk_size=5).chunk_size == 5


def test_options_default_to_the_code_defaults() -> None:
    options = plan_options(cohort="c-test")
    assert options.chunk_size == DEFAULT_CHUNK_SIZE
    assert not hasattr(options, "workers")


def test_resolve_chunk_size_prefers_an_explicit_value() -> None:
    assert resolve_chunk_size(5) == 5
    assert resolve_chunk_size(None) == DEFAULT_CHUNK_SIZE


def test_plan_command_honors_environment_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The regression itself: the written plan must record the declared settings."""
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "2")
    assert main(_plan_argv(tmp_path)) == 0
    payload = _parse_output(capsys)
    assert payload["chunk_size"] == 2
    assert payload["chunk_count"] == 2


# ----------------------------------------------------------------- plan / id


def test_plan_writes_a_bundle_not_one_file(tmp_path: Path) -> None:
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    plan_dirs = list((tmp_path / "metadata" / "plans").iterdir())
    assert len(plan_dirs) == 1
    bundle = plan_dirs[0]
    assert (bundle / "plan.json").is_file()
    assert (bundle / "roster" / "ciks.parquet").is_file()
    assert (bundle / "input" / "input_manifest.json").is_file()


def test_plan_command_limit_truncates_the_cohort(tmp_path: Path, capsys) -> None:
    assert main(_plan_argv(tmp_path, "--chunk-size", "2", "--limit", "2")) == 0
    payload = _parse_output(capsys)
    assert payload["row_count"] == 2


def test_a_limited_plan_and_a_full_plan_do_not_collide(tmp_path: Path, capsys) -> None:
    """The limit is applied before identity is derived, so the two stay distinct."""
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    full = _parse_output(capsys)["plan_id"]
    assert main(_plan_argv(tmp_path, "--chunk-size", "2", "--limit", "2")) == 0
    limited = _parse_output(capsys)["plan_id"]
    assert full != limited
    assert len(list((tmp_path / "metadata" / "plans").iterdir())) == 2


def test_replanning_the_same_cohort_is_idempotent(tmp_path: Path, capsys) -> None:
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    first = _parse_output(capsys)["plan_id"]
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    assert _parse_output(capsys)["plan_id"] == first
    assert len(list((tmp_path / "metadata" / "plans").iterdir())) == 1


# -------------------------------------------------------------------- status


def test_status_reports_progress_offline(tmp_path: Path, capsys) -> None:
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "status",
                "--cohort",
                _cohort_id(tmp_path),
                "--artifacts",
                str(tmp_path),
                "--chunk-size",
                "2",
            ]
        )
        == 0
    )
    payload = _parse_output(capsys)
    assert payload["planned_chunks"] == 2
    assert payload["completed_chunks"] == 0
    assert payload["mergeable"] is False
    assert payload["roster_id"]
    assert payload["schema_version"]


def test_status_accepts_an_explicit_plan_id(tmp_path: Path, capsys) -> None:
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    plan_id = _parse_output(capsys)["plan_id"]
    assert main(["status", "--plan-id", plan_id, "--artifacts", str(tmp_path)]) == 0
    assert _parse_output(capsys)["plan_id"] == plan_id


def test_changed_effective_chunking_fails_loudly(tmp_path: Path, capsys) -> None:
    """Refuses rather than reusing a differently chunked plan's checkpoints."""
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "status",
                "--cohort",
                _cohort_id(tmp_path),
                "--artifacts",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert "missing plan" in capsys.readouterr().err


def test_missing_plan_reports_an_error(tmp_path: Path, capsys) -> None:
    assert main(["status", "--plan-id", "deadbeef", "--artifacts", str(tmp_path)]) == 1
    assert "error:" in capsys.readouterr().err


def test_a_copied_bundle_names_its_own_plan(tmp_path: Path, capsys) -> None:
    """The bundle carries the manifest that declares the plan, so there is one source."""
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    plan_id = _parse_output(capsys)["plan_id"]
    destination = tmp_path / "out"
    main(
        [
            "distrib",
            "export",
            "--plan-id",
            plan_id,
            "--artifacts",
            str(tmp_path),
            "--workers",
            "1",
            "--destination",
            str(destination),
        ]
    )
    capsys.readouterr()
    bundle = destination / "worker-00"
    assert run_options(bundle_root=str(bundle)).plan_id == plan_id
    assert read_bundle_plan_id(bundle) == plan_id


def test_a_bundle_without_a_manifest_cannot_be_used(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert read_bundle_plan_id(empty) == ""
    with pytest.raises(ValueError, match="plan reference is required"):
        run_options(bundle_root=str(empty))


# ----------------------------------------------------------------------- run


def test_run_requires_a_chunk_selection_the_plan_has(tmp_path: Path, capsys) -> None:
    from edgar_sec.foundation.runtime.partitions import parse_id_selection

    assert parse_id_selection("0-2,5") == (0, 1, 2, 5)


def test_run_chunk_selection_is_parsed(
    tmp_path: Path, client: SubmissionsClient, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.run.build_client", lambda: client
    )
    _seed_session_for(monkeypatch)
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    plan_id = _parse_output(capsys)["plan_id"]

    assert (
        main(
            ["run", "--plan-id", plan_id, "--artifacts", str(tmp_path), "--chunks", "1"]
        )
        == 0
    )
    assert "total_chunks" in capsys.readouterr().out


def test_run_rejects_a_chunk_outside_the_plan(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.run.build_client", lambda: None
    )
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    plan_id = _parse_output(capsys)["plan_id"]
    assert (
        main(
            ["run", "--plan-id", plan_id, "--artifacts", str(tmp_path), "--chunks", "9"]
        )
        == 1
    )
    assert "not present in plan" in capsys.readouterr().err


def _seed_session_for(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    _seed_session(session)
    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.run.build_client",
        lambda: build_test_client(session),
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.augment.build_client",
        lambda: build_test_client(session),
    )


def build_test_client(session: FakeSession) -> SubmissionsClient:
    return SubmissionsClient(http=build_test_http(session))


# ------------------------------------------------------------------ options


def test_worker_count_stays_machine_derived_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A callable default means an explicit 0 would read as zero workers, not derive."""
    monkeypatch.setenv("RUNTIME_WORKERS", "3")
    assert run_options(plan_id="p").workers is None
    assert resolve_workers(run_options(plan_id="p").workers) == 3

    monkeypatch.delenv("RUNTIME_WORKERS")
    assert resolve_workers(None) >= 1


def test_main_dispatches_to_the_selected_command() -> None:
    parser = build_parser()
    assert parser.parse_args(["plan", "--cohort", "c-test"]).func.__name__ == (
        "<lambda>"
    )
    assert parser.parse_args(["merge", "--plan-id", "p"]).func.__name__ == "<lambda>"


def test_metadata_is_registered_in_the_launcher() -> None:
    import run as launcher

    entry = next(item for item in launcher.ENTRIES if item.id == "metadata")
    assert entry.module == "edgar_sec.pipelines.metadata_sync.operator"


def test_built_client_is_cached_against_the_registered_store() -> None:
    """`resolve_paths()` names a different directory, so reading it opens an empty store."""
    from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
    from edgar_sec.pipelines.metadata_sync.commands.client import build_client

    settings = resolve_runtime_settings()
    client = build_client()

    assert client.http.cache_dir == Path(settings.cache_root).resolve()
    assert client.http._cache is not None
    assert client.http._cache.ttl_s == settings.ttl_s
    assert settings.cache_root.name == "caches"
    assert client.http._cache.db_path.name == "responses.sqlite"


def test_dag_subcommand_dispatches(tmp_path: Path, capsys) -> None:
    assert main(["dag", "--root", str(tmp_path), "status"]) == 1
    assert "No active snapshot pointer" in capsys.readouterr().out
