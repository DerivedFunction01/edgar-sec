from __future__ import annotations

import json

import pytest

from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureOperationError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    _materialize_fixture_case,
    list_fixture_cases,
    list_fixture_summaries,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from tests.pipelines.document_acquisition.fixture_store.fixture_helpers import (
    append_test_case,
    initialize_test_fixture,
)


def test_reader_lists_and_materializes_selected_parser_body(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    body = b"<html><body>selected body</body></html>"
    append_test_case(paths, "fixture-a", "target-a", body)

    cases = list(list_fixture_cases(paths, fixture_id="fixture-a"))
    summaries = list(list_fixture_summaries(paths))
    output = tmp_path / "body.bin"
    materialized = _materialize_fixture_case(
        "fixture-a", "capture-1", "target-a", output, paths=paths
    )

    assert cases[0].body_sha256 == materialized.body_sha256
    assert cases[0].byte_size == len(body)
    assert summaries[0].case_count == 1
    assert summaries[0].capture_count == 1
    assert output.read_bytes() == body
    assert json.loads(paths.fixture_paths("fixture-a").manifest_path.read_text())[
        "fixture_kind"
    ] == ("document_acquisition.parser_bodies")


def test_reader_refuses_materialization_inside_fixture_root(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    append_test_case(paths, "fixture-a", "target-a", b"fixture")
    output = paths.fixture_paths("fixture-a").root / "body.bin"

    with pytest.raises(FixtureOperationError, match="inside managed artifacts"):
        _materialize_fixture_case(
            "fixture-a", "capture-1", "target-a", output, paths=paths
        )


def test_reader_refuses_symlink_destination(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    append_test_case(paths, "fixture-a", "target-a", b"fixture")
    target = tmp_path / "external-body.bin"
    target.write_bytes(b"existing")
    link = tmp_path / "body-link.bin"
    link.symlink_to(target)

    with pytest.raises(FixtureOperationError, match="symlink"):
        _materialize_fixture_case(
            "fixture-a", "capture-1", "target-a", link, paths=paths
        )
