"""Command grammar and fail-closed cohort command behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
import edgar_sec.infra.storage.cohort.ingestion as cohort_ingestion
import edgar_sec.infra.storage.cohort.operations as cohort_operations
from edgar_sec.infra.storage.cohort.operations import execute_set_operation
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.infra.storage.object_store.store import ObjectStore
from edgar_sec.pipelines.cohort import cli


def test_parser_exposes_documented_commands_and_nested_workspace_grammar() -> None:
    parser = cli.build_parser()
    commands = next(action.choices for action in parser._actions if action.choices)
    assert set(commands) == {
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
        "workspace",
        "merge",
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
