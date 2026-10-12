from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.domain.document_inventory.models import (
    CohortObservation,
    IndexWorkItem,
    InventoryCohort,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.pipelines.document_inventory import cli
from edgar_sec.pipelines.document_inventory.commands import fixture as fixture_command
from edgar_sec.pipelines.document_inventory.fixture_store.capture import (
    capture_index_pages,
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


def _patch_fixture_runtime(monkeypatch: pytest.MonkeyPatch, workers: int = 2):
    client = SimpleNamespace(close=lambda: None)
    resources = SimpleNamespace(workers=workers, worker_ceiling=workers)
    monkeypatch.setattr(fixture_command, "derive_resources", lambda: resources)
    monkeypatch.setattr(fixture_command, "_configured_http_client", lambda: client)
    return client


def test_configured_http_client_uses_shared_cache_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = SimpleNamespace(
        sec=object(), cache_root=tmp_path / "http-cache", ttl_s=456
    )
    client = object()
    calls = []

    class ClientFactory:
        @staticmethod
        def from_settings(sec, *, cache_dir, ttl_s):
            calls.append((sec, cache_dir, ttl_s))
            return client

    monkeypatch.setattr(fixture_command, "resolve_runtime_settings", lambda: settings)
    monkeypatch.setattr(fixture_command, "SecHttpClient", ClientFactory)

    assert fixture_command._configured_http_client() is client
    assert calls == [(settings.sec, settings.cache_root, settings.ttl_s)]


def test_parser_exposes_fixture_and_review_commands() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        ["fixture", "create", "--fixture", "f", "--catalog-plan", "p", "--limit", "2"]
    )
    assert args.command == "fixture"
    assert args.fixture_command == "create"
    assert args.limit == 2
    assert args.no_progress is False
    assert parser.parse_args(
        [
            "fixture",
            "fill",
            "--fixture",
            "f",
            "--catalog-plan",
            "p",
            "--no-progress",
        ]
    ).no_progress
    assert (
        parser.parse_args(
            ["review", "generate", "--fixture", "f", "--output", "review"]
        ).command
        == "review"
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


def test_lifecycle_commands_replace_the_all_in_one_builder() -> None:
    parser = cli.build_parser()
    subparsers = next(action for action in parser._actions if action.choices)
    assert {"project", "run", "status", "publish"} <= set(subparsers.choices)
    assert "build" not in subparsers.choices
    with pytest.raises(SystemExit):
        parser.parse_args(["build", "--catalog-plan", "p"])


def test_lifecycle_command_arguments_are_phase_specific() -> None:
    parser = cli.build_parser()
    project = parser.parse_args(["project", "--catalog-plan", "p"])
    assert project.branch == "main"
    assert project.base_snapshot_id is None
    run = parser.parse_args(["run", "--run-id", "r", "--confirm-stale-lock"])
    assert run.confirm_stale_lock
    assert run.retry_failures is False
    assert run.no_progress is False
    assert parser.parse_args(["run", "--run-id", "r", "--no-progress"]).no_progress
    publish = parser.parse_args(["publish", "--run-id", "r", "--branch", "alt"])
    assert publish.branch == "alt"
    assert publish.expected_branch_tip is None


def test_obsolete_placeholders_are_not_advertised() -> None:
    parser = cli.build_parser()
    for command in ("cohort", "index"):
        with pytest.raises(SystemExit):
            parser.parse_args([command])


def test_cli_query_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.snapshot.reader.query_accessions",
        lambda *args, **kwargs: [{"accession": "0000320193-23-000106"}],
    )
    assert (
        cli.main(
            [
                "query",
                "--form",
                "10-K",
                "--artifacts",
                str(tmp_path),
                "--json",
            ]
        )
        == 0
    )
    query_payload = json.loads(capsys.readouterr().out)
    assert query_payload["count"] == 1
    assert query_payload["results"][0]["accession"] == "0000320193-23-000106"


def test_direct_run_cli_dispatches_without_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatched = []
    monkeypatch.setattr(cli, "cmd_run", lambda args: dispatched.append(args) or 0)
    monkeypatch.setattr(
        "builtins.input", lambda *_args: pytest.fail("direct Run prompted")
    )

    assert cli.main(["run", "--run-id", "run-1", "--artifacts", str(tmp_path)]) == 0
    assert dispatched[0].run_id == "run-1"


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
    http_client = _patch_fixture_runtime(monkeypatch, workers=3)
    created: list[tuple[object, str]] = []
    captured: list[object] = []

    @contextmanager
    def managed(_socket: Path, *, http_client, max_connections):
        assert http_client is not None
        assert max_connections == 3
        yield broker

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.cohort_for_plan",
        lambda *_args: (plan, work, contribution_record),
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.managed_broker",
        managed,
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.create_index_fixture",
        lambda paths, fixture_id: created.append((paths, fixture_id)),
    )

    def capture(
        _cohort,
        *,
        fixture_id,
        paths,
        broker,
        contribution,
        workers,
        progress_callback=None,
    ):
        captured.append(
            (fixture_id, paths, broker, contribution, workers, progress_callback)
        )
        return IndexCaptureResult(1, 0, 1, 1, 1, ())

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.capture_index_pages",
        capture,
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
            "--json",
        ]
    )
    assert code == 0
    assert created == [(resolve_index_fixture_paths(tmp_path, "f"), "f")]
    assert captured[0][2] is broker
    assert captured[0][4] == 3
    assert captured[0][5] is None
    assert http_client is not None
    payload = json.loads(capsys.readouterr().out)
    assert payload["workers"] == 3
    assert payload["requested_accessions"] == 1
    assert payload["responses_added"] == 1


def test_create_resumes_existing_fixture_without_refetching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture_id = "f"
    accession = "0000123456-12-000001"
    url = "https://www.sec.gov/Archives/edgar/data/123456/index.html"
    work = InventoryCohort(
        observations=(
            CohortObservation(
                cohort_source_id="source",
                accession=AccessionNumber(accession),
                source_cik=Cik.from_raw("123456789"),
                form="10-K",
                filing_date=date(2023, 1, 1),
                report_date=None,
            ),
        ),
        accessions=(),
        sources=(),
        work_items=(IndexWorkItem(AccessionNumber(accession), url),),
    )
    contribution = _contribution()
    paths = resolve_index_fixture_paths(tmp_path, fixture_id)
    create_index_fixture(paths, fixture_id=fixture_id)

    class InitialBroker:
        def fetch(self, _url: str) -> dict[str, object]:
            return {"status": "ok", "payload": b"page", "cache_source": "network"}

    capture_index_pages(
        work,
        fixture_id=fixture_id,
        paths=paths,
        broker=InitialBroker(),
        contribution=contribution,
    )
    client = _patch_fixture_runtime(monkeypatch, workers=2)
    monkeypatch.setattr(
        fixture_command,
        "cohort_for_plan",
        lambda *_args: (
            {"plan_id": "p", "catalog_id": "c", "scope": "10-K"},
            work,
            contribution,
        ),
    )
    monkeypatch.setattr(
        fixture_command,
        "create_index_fixture",
        lambda *_args, **_kwargs: pytest.fail("existing fixture must not be reset"),
    )

    class NoFetchBroker:
        def fetch(self, _url: str) -> dict[str, object]:
            pytest.fail("cached fixture response must not be refetched")

    @contextmanager
    def managed(_socket: Path, *, http_client, max_connections):
        assert http_client is client
        assert max_connections == 2
        yield NoFetchBroker()

    monkeypatch.setattr(fixture_command, "managed_broker", managed)

    assert (
        cli.main(
            [
                "fixture",
                "create",
                "--fixture",
                fixture_id,
                "--catalog-plan",
                "p",
                "--artifacts",
                str(tmp_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["fixture_cache_hits"] == 1
    assert payload["responses_reused"] == 1
    assert payload["network_fetches"] == 0
    assert payload["cases_created"] == payload["members_created"] == 0


@pytest.mark.parametrize(
    ("tty", "json_output", "no_progress", "expected"),
    [
        (True, False, False, True),
        (True, False, True, False),
        (True, True, False, False),
        (False, False, False, False),
    ],
)
def test_fixture_progress_is_tty_only_and_suppression_is_honored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tty: bool,
    json_output: bool,
    no_progress: bool,
    expected: bool,
) -> None:
    bars = []
    _patch_fixture_runtime(monkeypatch)

    class Bar:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.updated = 0
            self.closed = False
            bars.append(self)

        def update(self, count: int) -> None:
            self.updated += count

        def set_postfix(self, _values: dict) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(fixture_command, "tqdm", Bar)
    monkeypatch.setattr(
        fixture_command,
        "sys",
        SimpleNamespace(stderr=SimpleNamespace(isatty=lambda: tty)),
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.cohort_for_plan",
        lambda *_args: (
            {"plan_id": "p", "catalog_id": "c", "scope": "10-K"},
            _cohort(),
            _contribution(),
        ),
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.create_index_fixture",
        lambda *_args, **_kwargs: None,
    )

    @contextmanager
    def managed(_socket: Path, *, http_client, max_connections):
        assert http_client is not None
        assert max_connections == 2
        yield object()

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.managed_broker",
        managed,
    )

    def capture(_cohort, *, progress_callback=None, **_kwargs):
        if progress_callback is not None:
            progress_callback({"status": "ok"})
        return IndexCaptureResult(1, 0, 1, 1, 1, ())

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.capture_index_pages",
        capture,
    )
    argv = [
        "fixture",
        "create",
        "--fixture",
        "f",
        "--catalog-plan",
        "p",
        "--artifacts",
        str(tmp_path),
    ]
    if json_output:
        argv.append("--json")
    if no_progress:
        argv.append("--no-progress")

    assert cli.main(argv) == 0
    assert bool(bars) is expected
    if bars:
        assert bars[0].kwargs["total"] == 1
        assert bars[0].updated == 1
        assert bars[0].closed
    capsys.readouterr()


def test_capture_failure_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_fixture_runtime(monkeypatch)
    work = _cohort()
    failure = IndexCaptureFailure(
        AccessionNumber("0000123456-12-000001"), "http_error", "not found"
    )

    @contextmanager
    def managed(_socket: Path, *, http_client, max_connections):
        assert http_client is not None
        assert max_connections == 2
        yield object()

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.cohort_for_plan",
        lambda *_args: ({}, work, _contribution()),
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.managed_broker",
        managed,
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.create_index_fixture",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_inventory.commands.fixture.capture_index_pages",
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
