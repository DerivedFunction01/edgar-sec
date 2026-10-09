"""Command grammar and fail-closed cohort command behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
import edgar_sec.pipelines.cohort.ingestion as cohort_ingestion
import edgar_sec.pipelines.cohort.operations as cohort_operations
from edgar_sec.pipelines.cohort.operations import execute_set_operation
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.infra.storage.object_store.store import ObjectStore
from edgar_sec.pipelines.cohort import cli


def test_parser_exposes_documented_commands_and_nested_workspace_grammar() -> None:
    parser = cli.build_parser()
    commands = next(action.choices for action in parser._actions if action.choices)
    assert set(commands) == {
        "doctor",
        "import",
        "list",
        "info",
        "rename",
        "tag",
        "untag",
        "delete",
        "query",
        "find",
        "sample",
        "sources",
        "diff",
        "family-index",
        "workspace",
        "repl",
        "merge",
        "maintain",
        "console",
    }
    workspace = commands["workspace"]
    nested = next(action.choices for action in workspace._actions if action.choices)
    assert set(nested) == {
        "init",
        "use",
        "current",
        "sessions",
        "bind",
        "let",
        "diff",
        "peek",
        "save",
        "list",
        "drop",
        "clear",
        "clean",
    }
    sample = parser.parse_args(
        [
            "sample",
            "--source",
            "universe",
            "--rate",
            "5",
            "--group-family",
            "--family-index",
            "company-family.parquet",
        ]
    )
    assert sample.group_family is True
    assert sample.family_index == "company-family.parquet"
    assert "first non-empty trimmed input-row name" in parser.description
    assert "official SEC sources on the left" in parser.description
    refresh = commands["sources"]
    source_commands = next(
        action.choices for action in refresh._actions if action.choices
    )
    assert set(source_commands) == {"refresh"}
    assert parser.parse_args(["sources", "refresh", "--source", "company_tickers"])
    diff = parser.parse_args(
        ["diff", "universe", "tickers", "--save-left-delta", "old"]
    )
    assert diff.left == "universe"
    assert diff.right == "tickers"
    assert diff.save_left_delta == "old"
    assert diff.save_right_delta is None
    maintain = parser.parse_args(["maintain", "--all"])
    assert maintain.all is True


@pytest.mark.parametrize("command", ["doctor", "maintain"])
def test_maintenance_commands_bypass_context_without_creating_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    paths = CohortPaths(tmp_path)
    monkeypatch.setattr(cli, "_paths", lambda: paths)
    monkeypatch.setattr(
        cli,
        "_context",
        lambda: pytest.fail("maintenance must not initialize a workspace context"),
    )

    arguments = [command] if command == "doctor" else [command, "--all"]
    assert cli.main(arguments) == 1
    captured = capsys.readouterr()
    assert "catalog is absent" in captured.err + captured.out
    assert not paths.cohorts_root.exists()


def test_maintenance_dispatches_without_workspace_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = CohortPaths(tmp_path)
    CohortCatalog(paths)
    orphan = paths.cohort_dir("c-0123456789abcdef")
    orphan.mkdir()
    monkeypatch.setattr(cli, "_paths", lambda: paths)
    monkeypatch.setattr(
        cli,
        "_context",
        lambda: pytest.fail("maintenance must not initialize a workspace context"),
    )

    assert cli.main(["maintain", "--clean-orphans"]) == 0
    assert not orphan.exists()
    assert "removed_orphans=1" in capsys.readouterr().out


def test_cli_identifier_resolution_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = CohortPaths(tmp_path)
    context = cli._Context(paths, CohortCatalog(paths), ObjectStore(paths.catalog_file))
    monkeypatch.setattr(cli, "_context", lambda: context)

    status = cli.main(["info", "c-1"])

    assert status == 1
    assert "hash lookups require at least 7 characters" in capsys.readouterr().err


def test_cli_startup_cleans_expired_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = CohortPaths(tmp_path)
    calls: list[int] = []
    clean = ObjectStore.clean_expired_sessions

    def tracked_clean(store: ObjectStore, max_age_seconds: int = 86400) -> int:
        calls.append(max_age_seconds)
        return clean(store, max_age_seconds)

    monkeypatch.setattr(cli, "resolve_paths", lambda: object())
    monkeypatch.setattr(cli, "resolve_cohort_paths", lambda *, project_paths: paths)
    monkeypatch.setattr(ObjectStore, "clean_expired_sessions", tracked_clean)

    assert cli.main(["workspace", "init", "session-a"]) == 0
    assert calls == [86400]
    assert ObjectStore(paths.catalog_file).get_active_session() == "session-a"


def test_repl_command_dispatches_to_workspace_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = CohortPaths(tmp_path)
    context = cli._Context(paths, CohortCatalog(paths), ObjectStore(paths.catalog_file))
    calls = []
    monkeypatch.setattr(cli, "_context", lambda: context)
    monkeypatch.setattr(
        "edgar_sec.pipelines.cohort.repl.run_repl",
        lambda *args: calls.append(args) or 0,
    )

    assert cli.main(["repl"]) == 0
    assert calls == [(paths, context.catalog, context.store)]


def test_list_renders_cohorts_as_a_grid(capsys: pytest.CaptureFixture[str]) -> None:
    records = [
        SimpleNamespace(
            cohort_id="c-1234567",
            name="sample",
            row_count=2,
            tags=("curated", "quarterly"),
        ),
        SimpleNamespace(cohort_id="c-7654321", name=None, row_count=1, tags=()),
    ]
    context = SimpleNamespace(
        catalog=SimpleNamespace(list_cohorts=lambda **_kwargs: records)
    )

    assert (
        cli._cmd_list(
            SimpleNamespace(
                tag=None,
                pinned_only=False,
                search=None,
                limit=20,
                offset=0,
            ),
            context,
        )
        == 0
    )

    assert [line.rstrip() for line in capsys.readouterr().out.splitlines()] == [
        "Cohorts",
        "  Cohort ID  Name    Rows  Tags",
        "  ---------  ------  ----  -----------------",
        "  c-1234567  sample  2     curated,quarterly",
        "  c-7654321  -       1",
    ]


def test_query_renders_members_and_preserves_count_offset(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    record = SimpleNamespace()
    members = [
        SimpleNamespace(cik_padded="0000000001", name="First Company"),
        SimpleNamespace(cik_padded="0000000002", name="Second Company"),
    ]
    monkeypatch.setattr(cli, "_resolve", lambda _context, _identifier: record)
    monkeypatch.setattr(
        cli, "_dataset", lambda _context, _record: Path("members.parquet")
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.cohort.query.query_cohort_members",
        lambda *_args, **_kwargs: (8, members),
    )

    assert (
        cli._cmd_query(
            SimpleNamespace(cohort="sample", cik=None, name=None, limit=2, offset=4),
            SimpleNamespace(),
        )
        == 0
    )

    assert [line.rstrip() for line in capsys.readouterr().out.splitlines()] == [
        "matches=8 offset=4",
        "Cohort Members",
        "  CIK         Name",
        "  ----------  --------------",
        "  0000000001  First Company",
        "  0000000002  Second Company",
    ]


def test_find_renders_matches_and_preserves_count_page(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    matches = [
        SimpleNamespace(
            cohort_id="c-1234567",
            cohort_name="sample",
            cik_padded="0000000001",
            name="First Company",
        ),
        SimpleNamespace(
            cohort_id="c-7654321",
            cohort_name=None,
            cik_padded="0000000002",
            name="Second Company",
        ),
    ]
    captured: dict[str, object] = {}

    def find(_catalog, **kwargs):
        captured.update(kwargs)
        return 7, matches

    monkeypatch.setattr("edgar_sec.pipelines.cohort.query.find_across_cohorts", find)

    assert (
        cli._cmd_find(
            SimpleNamespace(cik=None, name="Company", limit=2, page=3),
            SimpleNamespace(catalog=object()),
        )
        == 0
    )

    assert captured == {"cik": None, "name_substr": "Company", "limit": 2, "offset": 4}
    assert [line.rstrip() for line in capsys.readouterr().out.splitlines()] == [
        "matches=7 page=3",
        "Cohort Matches",
        "  Cohort ID  Cohort Name  CIK         Name",
        "  ---------  -----------  ----------  --------------",
        "  c-1234567  sample       0000000001  First Company",
        "  c-7654321               0000000002  Second Company",
    ]


def test_merge_serialize_does_not_require_a_cohort_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = CohortPaths(tmp_path)
    context = cli._Context(paths, CohortCatalog(paths), ObjectStore(paths.catalog_file))
    monkeypatch.setattr(cli, "_context", lambda: context)

    assert cli.main(["merge", "--expr", "A + B", "--serialize"]) == 0
    assert '"op":"union"' in capsys.readouterr().out


def test_clean_duration_accepts_units_and_rejects_malformed_values() -> None:
    assert cli._duration_seconds("2d") == 172800
    with pytest.raises(ValueError, match="duration"):
        cli._duration_seconds("soon")


def test_family_sampling_requires_an_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = CohortPaths(tmp_path)
    context = cli._Context(paths, CohortCatalog(paths), ObjectStore(paths.catalog_file))
    monkeypatch.setattr(cli, "_context", lambda: context)

    status = cli.main(
        ["sample", "--source", "universe", "--rate", "5", "--group-family"]
    )

    assert status == 1
    assert "family index is missing" in capsys.readouterr().err


def test_family_index_parser_dispatches_to_the_cohort_publisher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from edgar_sec.engine.company_family.assignment import FamilyAssignmentStats
    from edgar_sec.infra.storage.cohort.models import FamilyIndexRecord
    from edgar_sec.pipelines.cohort import family_index

    paths = CohortPaths(tmp_path)
    context = cli._Context(paths, CohortCatalog(paths), ObjectStore(paths.catalog_file))
    record = FamilyIndexRecord(
        universe_cohort_id="c-universe",
        family_index_id="a" * 32,
        rules_fingerprint="b" * 64,
        dataset_path="family_index/" + "a" * 32 + "/company_family.parquet",
        dataset_sha256="c" * 64,
        pinned_at="now",
    )
    stats = FamilyAssignmentStats(4, 2, 1, 1, 1, 0)
    monkeypatch.setattr(cli, "_context", lambda: context)
    monkeypatch.setattr(
        family_index,
        "publish_family_index",
        lambda *, catalog, paths: (
            family_index.FamilyIndexArtifact(record, Path("index.parquet")),
            stats,
        ),
    )

    assert cli.build_parser().parse_args(["family-index"]).command == "family-index"
    assert cli.main(["family-index"]) == 0
    output = capsys.readouterr().out
    assert "Family Index Published" in output
    assert "family_index_id" in output
    assert "dataset_path" in output
    assert "registrants" in output
    assert "unresolved_sponsors" in output


def test_sample_uses_derived_publication_with_source_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = CohortPaths(tmp_path / "artifacts")
    catalog = CohortCatalog(paths)
    context = cli._Context(paths, catalog, ObjectStore(paths.catalog_file))
    source = SimpleNamespace(cohort_id="c-source")
    monkeypatch.setattr(cli, "_context", lambda: context)
    monkeypatch.setattr(cli, "_source_record", lambda _context, _identifier: source)
    monkeypatch.setattr(
        cli, "_dataset", lambda _context, _record: tmp_path / "source.parquet"
    )
    publication: dict[str, object] = {}

    def materialize(_source_path, _output_path, **_kwargs):
        return 1

    def publish(_input_path, **kwargs):
        publication.update(kwargs)
        return SimpleNamespace(
            cohort=SimpleNamespace(
                cohort_id="c-sampled", origin_kind=kwargs["origin_kind"]
            )
        )

    monkeypatch.setattr(cohort_operations, "sample_cohort", materialize)
    monkeypatch.setattr(cohort_ingestion, "publish_derived_cohort", publish)

    assert (
        cli.main(
            [
                "sample",
                "--source",
                "universe",
                "--method",
                "random",
                "--limit",
                "1",
                "--seed",
                "19",
                "--name",
                "small-sample",
            ]
        )
        == 0
    )

    result = capsys.readouterr().out
    origin = publication["origin_details"]
    assert "c-sampled" in result
    assert publication["origin_kind"] == "sample"
    assert origin["source_cohort_id"] == "c-source"
    assert origin["sampling_method"] == "random"
    assert origin["rate_percent"] is None
    assert origin["sample_limit"] == 1
    assert origin["seed"] == 19


def test_union_name_selection_is_left_first_with_blank_fallback(
    tmp_path: Path,
) -> None:
    left = tmp_path / "official.parquet"
    right = tmp_path / "user.parquet"
    output = tmp_path / "combined.parquet"
    pq.write_table(
        pa.table(
            {
                "ordinal": [0, 1],
                "cik_padded": ["0000000001", "0000000002"],
                "name": ["", "Official SEC Name"],
            }
        ),
        left,
    )
    pq.write_table(
        pa.table(
            {
                "ordinal": [0, 1, 2],
                "cik_padded": ["0000000001", "0000000002", "0000000003"],
                "name": ["Fallback Name", "User Name", "Third Entity"],
            }
        ),
        right,
    )

    assert execute_set_operation(left, right, "union", output) == 3
    assert pq.read_table(output).to_pylist() == [
        {"ordinal": 0, "cik_padded": "0000000001", "name": "Fallback Name"},
        {"ordinal": 1, "cik_padded": "0000000002", "name": "Official SEC Name"},
        {"ordinal": 2, "cik_padded": "0000000003", "name": "Third Entity"},
    ]


def test_official_refresh_injects_client_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from edgar_sec.pipelines.cohort import sources

    paths = CohortPaths(tmp_path)
    context = cli._Context(paths, CohortCatalog(paths), ObjectStore(paths.catalog_file))
    injected_client = object()
    observed: dict[str, object] = {}

    def refresh(source, *, client, paths, catalog):
        observed.update(source=source, client=client, paths=paths, catalog=catalog)
        return SimpleNamespace(cohort_id="c-refreshed")

    monkeypatch.setattr(cli, "_context", lambda: context)
    monkeypatch.setattr(sources, "refresh_official_source", refresh)

    assert (
        cli.main(
            ["sources", "refresh", "--source", "company_tickers"],
            source_client=injected_client,
        )
        == 0
    )
    assert observed == {
        "source": "company_tickers",
        "client": injected_client,
        "paths": paths,
        "catalog": context.catalog,
    }
    assert "active company_tickers: c-refreshed" in capsys.readouterr().out


def test_diff_aliases_saves_both_named_membership_deltas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from edgar_sec.pipelines.cohort.query import query_cohort_members
    from edgar_sec.pipelines.cohort.sources import refresh_official_source

    paths = CohortPaths(tmp_path / "artifacts")
    catalog = CohortCatalog(paths)
    context = cli._Context(paths, catalog, ObjectStore(paths.catalog_file))

    class OfflineClient:
        payloads = {
            "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt": (
                b"Alpha Corp:1:\nBeta Corp:2:\n"
            ),
            "https://www.sec.gov/files/company_tickers.json": (
                b'{"0":{"cik_str":2,"ticker":"B","title":"Beta Corp"},'
                b'"1":{"cik_str":3,"ticker":"C","title":"Gamma Corp"}}'
            ),
        }

        def get_bytes(self, url: str, *, mutable: bool) -> bytes:
            assert mutable is True
            return self.payloads[url]

    client = OfflineClient()
    for source in ("cik_lookup", "company_tickers"):
        refresh_official_source(source, client=client, paths=paths, catalog=catalog)
    monkeypatch.setattr(cli, "_context", lambda: context)

    assert (
        cli.main(
            [
                "diff",
                "universe",
                "tickers",
                "--save-left-delta",
                "universe-only",
                "--save-right-delta",
                "tickers-only",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert output.count("2 CIKs") == 2
    assert "intersection" in output
    assert "left only" in output
    assert "right only" in output
    assert "union" in output
    assert "0000000001" in output
    assert "0000000003" in output
    assert "Alpha Corp" in output
    assert "Gamma Corp" in output
    left_delta = catalog.resolve_cohort_identifier("universe-only")
    right_delta = catalog.resolve_cohort_identifier("tickers-only")
    left_count, left_members = query_cohort_members(
        paths.resolve_relative_path(left_delta.dataset_path)
    )
    right_count, right_members = query_cohort_members(
        paths.resolve_relative_path(right_delta.dataset_path)
    )
    assert (
        left_count,
        [(member.cik_padded, member.name) for member in left_members],
    ) == (
        1,
        [("0000000001", "Alpha Corp")],
    )
    assert (
        right_count,
        [(member.cik_padded, member.name) for member in right_members],
    ) == (1, [("0000000003", "Gamma Corp")])
