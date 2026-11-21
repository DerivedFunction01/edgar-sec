from __future__ import annotations

import json

import pytest

from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    get_fixture_case,
    iter_fixture_cases,
    list_fixture_summaries,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.foundation.serialization import canonical_json
from tests.pipelines.document_acquisition.fixture_store.fixture_helpers import (
    append_test_case,
    initialize_test_fixture,
)


def test_fixture_discovery_is_sorted_and_summaries_are_capture_scoped(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-z")
    initialize_test_fixture(paths, "fixture-a")
    append_test_case(paths, "fixture-z", "target-b", b"b")
    append_test_case(paths, "fixture-z", "target-a", b"a")
    append_test_case(
        paths,
        "fixture-z",
        "target-c",
        b"c",
        capture_id="capture-2",
    )

    cases = list(iter_fixture_cases(paths))
    summaries = list_fixture_summaries(paths)

    assert [(case.fixture_id, case.capture_id, case.target_id) for case in cases] == [
        ("fixture-z", "capture-1", "target-a"),
        ("fixture-z", "capture-1", "target-b"),
        ("fixture-z", "capture-2", "target-c"),
    ]
    assert [item.fixture_id for item in summaries] == ["fixture-a", "fixture-z"]
    assert summaries[1].capture_count == 2
    assert summaries[1].case_count == 3


def test_fixture_case_lookup_uses_capture_and_target_identity(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    append_test_case(paths, "fixture-a", "target-a", b"first")
    append_test_case(
        paths,
        "fixture-a",
        "target-a",
        b"second",
        capture_id="capture-2",
    )

    case = get_fixture_case(paths, "fixture-a", "capture-2", "target-a")

    assert case.capture_id == "capture-2"
    assert case.byte_size == len(b"second")
    with pytest.raises(FixtureStoreError, match="fixture case not found"):
        get_fixture_case(paths, "fixture-a", "capture-1", "missing")


def test_discovery_ignores_old_schema_fixture_without_migration(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    manifest_path = paths.fixture_paths("fixture-a").manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fixture_kind"] = "document_acquisition.source_responses"
    manifest["details"]["store_schema_version"] = 1
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")

    assert list_fixture_summaries(paths) == ()


def test_fixture_case_metadata_carries_the_plan_dates(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-dates")
    append_test_case(
        paths,
        "fixture-dates",
        "target-a",
        b"body",
        filing_date="2002-11-29",
        report_date="2002-11-28",
    )
    append_test_case(
        paths,
        "fixture-dates",
        "target-b",
        b"body",
        filing_date=None,
        report_date=None,
    )

    cases = {case.target_id: case for case in iter_fixture_cases(paths)}

    assert cases["target-a"].filing_date == "2002-11-29"
    assert cases["target-a"].report_date == "2002-11-28"
    assert cases["target-b"].filing_date is None
    assert cases["target-b"].report_date is None
