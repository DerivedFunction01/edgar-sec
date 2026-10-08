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
    augment_options,
    plan_options,
    read_bundle_plan_id,
    resolve_chunk_size,
    run_options,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_NAME,
    SOURCE_UNIVERSE_URL,
    SOURCE_URL,
    refresh_cik_lookup_universe,
    refresh_company_tickers,
)
from edgar_sec.pipelines.metadata_sync.worker import resolve_workers
from tests.support import (
    FakeSession,
    build_test_http,
    cik_payload,
    fixture_path,
    published_universe,
)

COMMANDS = (
    "plan",
    "status",
    "run",
    "merge",
    "distrib",
    "augment",
    "sources",
    "family-index",
    "dag",
)

SOURCE_TICKERS = {
    "0": {"cik_str": "37996", "ticker": "F", "title": "FORD MOTOR CO"},
    "1": {"cik_str": "20", "ticker": "KTC", "title": "K Tron International Inc"},
    "2": {"cik_str": "5555", "ticker": "NEW", "title": "NEWCO INC"},
}

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


def _plan_argv(artifacts: Path, *extra: str) -> list[str]:
    return [
        "plan",
        "--input",
        str(fixture_path("cik_sec_mini.csv")),
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


def test_sources_registers_refresh_and_compare() -> None:
    sources = _subparser("sources")
    nested = next(
        act.choices for act in sources._actions if getattr(act, "choices", None)
    )
    assert set(nested) == {"refresh", "compare"}


def test_distrib_registers_distribution_subcommands() -> None:
    distrib = _subparser("distrib")
    nested = next(
        act.choices for act in distrib._actions if getattr(act, "choices", None)
    )
    assert set(nested) == {"export", "worker", "import", "list", "commands"}


def test_a_plan_needs_a_cohort_reference() -> None:
    for command in ("plan", "augment"):
        assert {"--input", "--roster", "--universe"} <= _flags(command)


def test_a_cohort_reference_is_exclusive() -> None:
    """Two cohort sources would be two answers to one question."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["plan", "--input", "a.csv", "--roster", "r1"])


def test_the_universe_cannot_be_combined_with_another_cohort() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["plan", "--universe", "--input", "a.csv"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["plan", "--universe", "--roster", "r1"])


def test_execution_commands_re_derive_from_the_universe() -> None:
    for command in ("status", "run", "merge"):
        assert "--universe" in _flags(command)


def test_a_plan_with_no_cohort_reference_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["plan"])


def test_execution_commands_accept_a_plan_reference() -> None:
    for command in ("status", "run", "merge"):
        assert {"--plan-id", "--bundle", "--input"} <= _flags(command)


def test_augment_needs_a_base_but_not_a_hand_typed_snapshot_id() -> None:
    """Requiring it forced an operator to invent an id on every surface."""
    assert "--base-snapshot-id" in _flags("augment")
    assert "--new-snapshot-id" in _flags("augment")

    parsed = build_parser().parse_args(
        [
            "augment",
            "--input",
            "x.csv",
            "--base-snapshot-id",
            "base",
        ]
    )
    assert parsed.new_snapshot_id == ""


def test_augment_still_refuses_to_run_without_a_base() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["augment", "--input", "x.csv"])


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
    args = build_parser().parse_args(["plan", "--input", "x.csv"])
    assert args.chunk_size is None


def test_options_fall_back_to_the_settings_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    options = plan_options(input_path="x.csv")
    assert options.chunk_size == 7


def test_explicit_flags_override_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_CHUNK_SIZE", "7")
    assert plan_options(input_path="x.csv", chunk_size=5).chunk_size == 5


def test_options_default_to_the_code_defaults() -> None:
    options = plan_options(input_path="x.csv")
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


# ------------------------------------------------------------- plan / universe


def _publish_universe_snapshot(session: FakeSession, tmp_path: Path) -> None:
    session.register_bytes(
        SOURCE_UNIVERSE_URL, fixture_path("cik_lookup_universe_mini.txt").read_bytes()
    )
    metadata = resolve_metadata_paths(tmp_path)
    refresh_cik_lookup_universe(
        metadata_paths=metadata, client=build_test_http(session)
    )


def test_plan_over_the_universe_needs_a_published_snapshot(
    tmp_path: Path, capsys
) -> None:
    """Planning is network-free, so an absent snapshot is a message, not a fetch."""
    assert main(["plan", "--universe", "--artifacts", str(tmp_path)]) == 1
    assert "sources refresh --source cik_lookup" in capsys.readouterr().err


def test_plan_over_the_universe_covers_every_registrant(
    session: FakeSession, tmp_path: Path, capsys
) -> None:
    _publish_universe_snapshot(session, tmp_path)
    assert main(["plan", "--universe", "--artifacts", str(tmp_path)]) == 0
    payload = _parse_output(capsys)
    assert payload["row_count"] == 12


def test_plan_over_the_universe_is_idempotent(
    session: FakeSession, tmp_path: Path, capsys
) -> None:
    _publish_universe_snapshot(session, tmp_path)
    main(["plan", "--universe", "--artifacts", str(tmp_path)])
    first = _parse_output(capsys)["plan_id"]
    main(["plan", "--universe", "--artifacts", str(tmp_path)])
    assert _parse_output(capsys)["plan_id"] == first


def test_a_universe_plan_and_a_csv_plan_do_not_collide(
    session: FakeSession, tmp_path: Path, capsys
) -> None:
    _publish_universe_snapshot(session, tmp_path)
    main(["plan", "--universe", "--artifacts", str(tmp_path)])
    universe = _parse_output(capsys)["plan_id"]
    main(_plan_argv(tmp_path, "--chunk-size", "2"))
    curated = _parse_output(capsys)["plan_id"]
    assert universe != curated


def test_a_universe_limit_bounds_the_plan(
    session: FakeSession, tmp_path: Path, capsys
) -> None:
    _publish_universe_snapshot(session, tmp_path)
    assert (
        main(
            [
                "plan",
                "--universe",
                "--limit",
                "3",
                "--chunk-size",
                "2",
                "--artifacts",
                str(tmp_path),
            ]
        )
        == 0
    )
    payload = _parse_output(capsys)
    assert payload["row_count"] == 3
    assert payload["chunk_count"] == 2


# -------------------------------------------------------------------- status


def test_status_reports_progress_offline(tmp_path: Path, capsys) -> None:
    assert main(_plan_argv(tmp_path, "--chunk-size", "2")) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "status",
                "--input",
                str(fixture_path("cik_sec_mini.csv")),
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
                "--input",
                str(fixture_path("cik_sec_mini.csv")),
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


# ------------------------------------------------------------------- sources


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

    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.sources.refresh_company_tickers",
        fake_refresh,
    )
    assert main(["sources", "refresh", "--artifacts", str(tmp_path)]) == 0
    assert captured["artifacts_root"] == tmp_path.resolve()


def test_sources_refresh_reports_a_failure_as_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def explode(**_kwargs):
        raise ValueError("source unavailable")

    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.sources.refresh_company_tickers",
        explode,
    )
    assert main(["sources", "refresh", "--artifacts", str(tmp_path)]) == 1
    assert "error: source unavailable" in capsys.readouterr().err


def test_sources_refresh_routes_the_universe_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--source cik_lookup`` must reach the universe publisher, not the ticker one."""
    captured: dict[str, object] = {}

    def fake_universe(*, metadata_paths, client=None):
        captured["artifacts_root"] = metadata_paths.artifacts_root
        return {"source": "cik_lookup", "snapshot_id": "u1", "validation_status": "ok"}

    monkeypatch.setattr(
        "edgar_sec.pipelines.metadata_sync.commands.sources.refresh_cik_lookup_universe",
        fake_universe,
    )
    assert (
        main(
            [
                "sources",
                "refresh",
                "--source",
                "cik_lookup",
                "--artifacts",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert captured["artifacts_root"] == tmp_path.resolve()


def test_sources_compare_publishes_a_roster_and_the_csv_export(
    session: FakeSession, tmp_path: Path, capsys
) -> None:
    """The roster dataset is the carrier; the CSV remains the export."""
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
    summary = _parse_output(capsys)
    assert summary["source"] == SOURCE_NAME
    assert summary["new_cik_count"] == 1

    registry_id = summary["registry_id"]
    for dataset in (
        "listing_observations",
        "registrant_registry",
        "new_ciks",
        "augmentation_worklist",
        "effective_ciks",
    ):
        assert metadata.registry_dataset(registry_id, dataset).is_file()
    assert metadata.effective_input_file(registry_id).is_file()
    assert summary["roster_id"]


def test_a_published_roster_can_be_planned_and_merged(
    session: FakeSession, tmp_path: Path, capsys, monkeypatch
) -> None:
    """Nothing downstream reads the compare artifacts unless a plan consumes them."""
    session.register_bytes(SOURCE_URL, json.dumps(SOURCE_TICKERS).encode("utf-8"))
    metadata = resolve_metadata_paths(tmp_path)
    published = refresh_company_tickers(
        metadata_paths=metadata, client=build_test_http(session)
    )
    main(
        [
            "sources",
            "compare",
            "--input",
            str(fixture_path("cik_sec_mini.csv")),
            "--source-manifest",
            str(metadata.source_manifest_file(SOURCE_NAME, published["snapshot_id"])),
            "--artifacts",
            str(tmp_path),
        ]
    )
    registry_id = _parse_output(capsys)["registry_id"]
    capsys.readouterr()

    assert (
        main(
            [
                "plan",
                "--roster",
                registry_id,
                "--artifacts",
                str(tmp_path),
                "--chunk-size",
                "2",
            ]
        )
        == 0
    )
    planned = _parse_output(capsys)
    assert planned["row_count"] == 5

    _seed_session_for(monkeypatch)
    session.register(submissions_url("0000005555"), cik_payload("0000005555", "NEWCO"))
    assert (
        main(["run", "--plan-id", planned["plan_id"], "--artifacts", str(tmp_path)])
        == 0
    )
    capsys.readouterr()
    assert (
        main(["merge", "--plan-id", planned["plan_id"], "--artifacts", str(tmp_path)])
        == 0
    )
    merged = _parse_output(capsys)
    assert merged["row_count"] == 5
    manifest_file = metadata.snapshot_manifest(merged["snapshot_id"])
    published_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert published_manifest["row_count"] == 5
    assert published_manifest["registry_id"] == registry_id
    assert published_manifest["cik_index_path"].endswith("ciks.parquet")


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


# ------------------------------------------------------------------ options


def test_augment_options_carry_the_lineage_binding() -> None:
    options, lineage = augment_options(
        input_path="x.csv",
        base_snapshot_id="base",
        new_snapshot_id="next",
    )
    assert lineage["parent_snapshot_id"] == "base"
    assert lineage["registry_id"] == ""
    assert options.chunk_size == DEFAULT_CHUNK_SIZE


def test_augment_options_need_no_new_snapshot_id() -> None:
    """Omitting it is how the caller asks for the derived delta plan id."""
    _options, lineage = augment_options(input_path="x.csv", base_snapshot_id="base")
    assert lineage["parent_snapshot_id"] == "base"


def test_augment_options_record_a_registry_lineage() -> None:
    _options, lineage = augment_options(
        registry_id="reg1", base_snapshot_id="base", new_snapshot_id="next"
    )
    assert lineage["registry_id"] == "reg1"
    assert lineage["parent_snapshot_id"] == "base"


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
    assert parser.parse_args(["plan", "--input", "x.csv"]).func.__name__ == ("<lambda>")
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


# ------------------------------------------------------------- family index


def test_family_index_publishes_an_assignment_and_reports_it(
    tmp_path: Path, capsys
) -> None:
    """The counts an operator needs to judge the artifact come back from its manifest."""
    published_universe(tmp_path)
    assert main(["family-index", "--artifacts", str(tmp_path)]) == 0
    summary = _parse_output(capsys)
    metadata = resolve_metadata_paths(tmp_path)
    manifest_file = metadata.family_index_manifest(summary["family_index_id"])
    assignment_file = metadata.family_index_file(summary["family_index_id"])
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert assignment_file.is_file()
    assert manifest_file.is_file()
    assert summary["registrants"] > 0
    assert manifest["rules_fingerprint"]
    assert manifest["dataset_sha256"]


def test_family_index_is_idempotent_across_runs(tmp_path: Path, capsys) -> None:
    published_universe(tmp_path)
    assert main(["family-index", "--artifacts", str(tmp_path)]) == 0
    first = _parse_output(capsys)
    assert main(["family-index", "--artifacts", str(tmp_path)]) == 0
    second = _parse_output(capsys)
    assert first["family_index_id"] == second["family_index_id"]
    metadata = resolve_metadata_paths(tmp_path)
    manifest = json.loads(
        metadata.family_index_manifest(first["family_index_id"]).read_text(
            encoding="utf-8"
        )
    )
    assert manifest["assignment_sha256"]


def test_family_index_refuses_without_a_published_universe(
    tmp_path: Path, capsys
) -> None:
    assert main(["family-index", "--artifacts", str(tmp_path)]) == 1
    assert "cik_lookup" in capsys.readouterr().err


def test_dag_subcommand_dispatches(tmp_path: Path, capsys) -> None:
    assert main(["dag", "--root", str(tmp_path), "status"]) == 1
    assert "No active snapshot pointer" in capsys.readouterr().out
