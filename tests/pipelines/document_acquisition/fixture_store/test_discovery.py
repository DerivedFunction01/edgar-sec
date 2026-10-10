import io

import pytest

import edgar_sec.pipelines.document_acquisition.fixture_store.discovery as discovery_module
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    get_fixture_case,
    iter_fixture_cases,
    iter_fixture_ids,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
    initialize_fixture,
)


def _append_case(paths, fixture_id, capture, case_factory, target_id):
    case = case_factory(target_id)
    response = f"{fixture_id}:{capture['capture_id']}:{target_id}".encode()
    append_fixture_case(
        paths,
        fixture_id,
        capture,
        case,
        io.BytesIO(response),
        max_response_bytes=len(response),
    )


def test_listing_and_filters_are_deterministic(
    acquisition_paths, capture_values, case_factory
) -> None:
    for fixture_id in ("fixture_z", "fixture_a"):
        initialize_fixture(acquisition_paths, fixture_id)
    _append_case(
        acquisition_paths, "fixture_z", capture_values, case_factory, "target_b"
    )
    _append_case(
        acquisition_paths, "fixture_z", capture_values, case_factory, "target_a"
    )
    later_capture = {**capture_values, "capture_id": "capture_2"}
    _append_case(
        acquisition_paths, "fixture_z", later_capture, case_factory, "target_a"
    )
    _append_case(
        acquisition_paths, "fixture_a", capture_values, case_factory, "target_c"
    )

    assert list(iter_fixture_ids(acquisition_paths)) == [
        "fixture_a",
        "fixture_z",
    ]
    listed = list(iter_fixture_cases(acquisition_paths))
    assert [(item.fixture_id, item.capture_id, item.target_id) for item in listed] == [
        ("fixture_a", "capture_1", "target_c"),
        ("fixture_z", "capture_1", "target_a"),
        ("fixture_z", "capture_1", "target_b"),
        ("fixture_z", "capture_2", "target_a"),
    ]
    assert [
        (item.fixture_id, item.capture_id, item.target_id)
        for item in iter_fixture_cases(
            acquisition_paths,
            fixture_id="fixture_z",
            capture_id="capture_1",
            target_id="target_b",
        )
    ] == [("fixture_z", "capture_1", "target_b")]
    assert list(iter_fixture_cases(acquisition_paths, target_id="target_a")) == [
        listed[1],
        listed[3],
    ]


def test_exact_lookup_returns_only_the_requested_case(
    acquisition_paths, capture_values, case_factory
) -> None:
    initialize_fixture(acquisition_paths, "fixture_exact")
    _append_case(
        acquisition_paths, "fixture_exact", capture_values, case_factory, "target_1"
    )
    _append_case(
        acquisition_paths, "fixture_exact", capture_values, case_factory, "target_2"
    )

    result = get_fixture_case(
        acquisition_paths, "fixture_exact", "capture_1", "target_2"
    )
    assert (result.fixture_id, result.capture_id, result.target_id) == (
        "fixture_exact",
        "capture_1",
        "target_2",
    )
    with pytest.raises(FixtureStoreError, match="fixture case not found"):
        get_fixture_case(
            acquisition_paths, "fixture_exact", "capture_missing", "target_2"
        )


def test_discovery_is_read_only_and_queries_no_response_blobs(
    acquisition_paths, capture_values, case_factory, monkeypatch
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_readonly")
    _append_case(
        acquisition_paths,
        "fixture_readonly",
        capture_values,
        case_factory,
        "target_1",
    )
    before = fixture.storage_path.stat()
    traced: list[str] = []
    original_open = discovery_module.open_fixture

    def traced_open(paths, fixture_id, *, readonly):
        assert readonly is True
        fixture_paths, connection = original_open(paths, fixture_id, readonly=readonly)
        connection.set_trace_callback(traced.append)
        return fixture_paths, connection

    monkeypatch.setattr(discovery_module, "open_fixture", traced_open)
    assert len(list(iter_fixture_cases(acquisition_paths))) == 1
    after = fixture.storage_path.stat()

    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    metadata_sql = [
        statement.upper()
        for statement in traced
        if statement.lstrip().upper().startswith("SELECT")
        and "CASES" in statement.upper()
    ]
    assert metadata_sql
    assert all("RESPONSE_BODIES" not in statement for statement in metadata_sql)
    assert all("COMPRESSED_BODY" not in statement for statement in metadata_sql)


def test_discovery_rejects_invalid_ids_symlink_roots_and_incomplete_fixtures(
    acquisition_paths,
) -> None:
    with pytest.raises(ValueError, match="fixture_id"):
        list(iter_fixture_cases(acquisition_paths, fixture_id="../escape"))

    initialize_fixture(acquisition_paths, "fixture_real")
    link = acquisition_paths.fixtures_root / "fixture_link"
    link.symlink_to(
        acquisition_paths.fixture_root("fixture_real"), target_is_directory=True
    )
    with pytest.raises(FixtureStoreError, match="symlink"):
        list(iter_fixture_ids(acquisition_paths))

    link.unlink()
    (acquisition_paths.fixtures_root / "fixture_incomplete").mkdir()
    with pytest.raises(FixtureStoreError, match="missing or incomplete"):
        list(iter_fixture_ids(acquisition_paths))
    with pytest.raises(FixtureStoreError, match="missing or incomplete"):
        list(iter_fixture_cases(acquisition_paths))


def test_missing_fixture_registry_is_an_empty_listing(acquisition_paths) -> None:
    assert list(iter_fixture_ids(acquisition_paths)) == []
    assert list(iter_fixture_cases(acquisition_paths)) == []
