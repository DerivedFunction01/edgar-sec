import hashlib
import io
import sqlite3

import pytest

from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
    initialize_fixture,
)


def test_append_compresses_every_body_and_deduplicates(
    acquisition_paths, capture_values, case_factory
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_storage")
    response = (b"<html>filing\x00" * 10000) + b"end"
    body = append_fixture_case(
        acquisition_paths,
        "fixture_storage",
        capture_values,
        case_factory(),
        io.BytesIO(response),
        max_response_bytes=len(response),
    )

    assert body is not None
    assert body.response_sha256 == hashlib.sha256(response).hexdigest()
    assert body.byte_size == len(response)
    assert body.stored_byte_size < body.byte_size
    assert not body.reused
    with sqlite3.connect(fixture.storage_path) as connection:
        stored = connection.execute(
            "SELECT storage_codec, stored_sha256, stored_byte_size, length(compressed_body) "
            "FROM response_bodies"
        ).fetchone()
        assert stored == (
            "zstd",
            body.stored_sha256,
            body.stored_byte_size,
            body.stored_byte_size,
        )

    repeated = append_fixture_case(
        acquisition_paths,
        "fixture_storage",
        capture_values,
        case_factory("target_2"),
        io.BytesIO(response),
        max_response_bytes=len(response),
    )
    assert repeated is not None and repeated.reused
    with sqlite3.connect(fixture.storage_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM response_bodies").fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 2


def test_failure_case_without_body_is_immutable(
    acquisition_paths, capture_values, case_factory
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_failure")
    failed = case_factory()
    failed.update(
        acquisition_status="failed",
        selected_sha256=None,
        selected_byte_size=None,
        selected_filename=None,
    )
    assert (
        append_fixture_case(
            acquisition_paths,
            "fixture_failure",
            capture_values,
            failed,
            None,
            max_response_bytes=100,
        )
        is None
    )
    with sqlite3.connect(fixture.storage_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM cases")


def test_limits_mismatches_and_conflicts_leave_no_partial_body(
    acquisition_paths, capture_values, case_factory
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_atomic")
    response = b"oversized"
    with pytest.raises(FixtureStoreError, match="max_response_bytes"):
        append_fixture_case(
            acquisition_paths,
            "fixture_atomic",
            capture_values,
            case_factory(),
            io.BytesIO(response),
            max_response_bytes=len(response) - 1,
        )
    mismatched = case_factory()
    mismatched["response_sha256"] = "f" * 64
    with pytest.raises(FixtureStoreError, match="does not match its source stream"):
        append_fixture_case(
            acquisition_paths,
            "fixture_atomic",
            capture_values,
            mismatched,
            io.BytesIO(response),
            max_response_bytes=len(response),
        )

    append_fixture_case(
        acquisition_paths,
        "fixture_atomic",
        capture_values,
        case_factory(),
        io.BytesIO(response),
        max_response_bytes=len(response),
    )
    conflicting = case_factory()
    conflicting["request_id"] = "different"
    different_response = b"new body not to retain"
    with pytest.raises(FixtureStoreError, match="conflicting immutable cases"):
        append_fixture_case(
            acquisition_paths,
            "fixture_atomic",
            capture_values,
            conflicting,
            io.BytesIO(different_response),
            max_response_bytes=len(different_response),
        )
    with sqlite3.connect(fixture.storage_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM response_bodies").fetchone()[0]
            == 1
        )


def test_response_capture_reads_in_bounded_chunks(
    acquisition_paths, capture_values, case_factory
) -> None:
    class BoundedSource(io.BytesIO):
        maximum_read = 0

        def read(self, size=-1):
            self.maximum_read = max(self.maximum_read, size)
            return super().read(size)

    initialize_fixture(acquisition_paths, "fixture_bounded")
    source = BoundedSource(b"x" * (DEFAULT_IO_CHUNK_SIZE * 5 + 13))
    append_fixture_case(
        acquisition_paths,
        "fixture_bounded",
        capture_values,
        case_factory(),
        source,
        max_response_bytes=DEFAULT_IO_CHUNK_SIZE * 6,
    )
    assert 0 < source.maximum_read <= DEFAULT_IO_CHUNK_SIZE


def test_related_lazy_index_response_is_stored(
    acquisition_paths, capture_values, case_factory
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_related")
    index_response = b"<index><filing/></index>"
    index_digest = hashlib.sha256(index_response).hexdigest()
    not_filed = case_factory()
    not_filed.update(
        acquisition_status="not_filed",
        optional=1,
        catalog_direct_selection="exact_form_with_lazy_index",
        index_response_sha256=index_digest,
        selected_sha256=None,
        selected_byte_size=None,
        selected_filename=None,
    )
    append_fixture_case(
        acquisition_paths,
        "fixture_related",
        capture_values,
        not_filed,
        None,
        max_response_bytes=1024,
        related_responses={"index_response_sha256": io.BytesIO(index_response)},
    )
    with sqlite3.connect(fixture.storage_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM response_bodies").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT response_sha256 FROM cases").fetchone()[0]
            is None
        )


def test_v3_lazy_direct_resolution_stores_distinct_evidence(
    acquisition_paths, capture_values, case_factory
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_lazy_direct")
    source = b"initial catalog response"
    index = b"lazy filing index"
    selected = b"selected filing response"
    source_digest = hashlib.sha256(source).hexdigest()
    index_digest = hashlib.sha256(index).hexdigest()
    selected_digest = hashlib.sha256(selected).hexdigest()
    case = case_factory()
    case.update(
        catalog_direct_selection="exact_form_with_lazy_index",
        resolution_schema_version="1",
        screen_kind="html_cover",
        screen_result="unverifiable",
        index_parser_version="index-parser-v1",
        matching_entry_ids_json='["entry_1"]',
        index_response_sha256=index_digest,
        selected_response_sha256=selected_digest,
        selected_retrieval_mode="direct_url",
        selected_url="https://www.sec.gov/selected.htm",
        selected_sha256=selected_digest,
        selected_byte_size=len(selected),
    )

    append_fixture_case(
        acquisition_paths,
        "fixture_lazy_direct",
        capture_values,
        case,
        io.BytesIO(source),
        max_response_bytes=1024,
        related_responses={
            "index_response_sha256": io.BytesIO(index),
            "selected_response_sha256": io.BytesIO(selected),
        },
    )

    assert len({source_digest, index_digest, selected_digest}) == 3
    with sqlite3.connect(fixture.storage_path) as connection:
        assert set(
            row[0]
            for row in connection.execute("SELECT response_sha256 FROM response_bodies")
        ) == {source_digest, index_digest, selected_digest}
        row = connection.execute(
            "SELECT response_sha256, index_response_sha256, "
            "selected_response_sha256 FROM cases"
        ).fetchone()
        assert row == (source_digest, index_digest, selected_digest)


def test_v3_lazy_bundle_resolution_preserves_target_retrieval_identity(
    acquisition_paths, capture_values, case_factory
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_lazy_bundle")
    source = b"initial catalog response"
    index = b"lazy filing index"
    selected_bundle = b"bundle response with extracted child"
    selected_child = b"extracted selected filing"
    source_digest = hashlib.sha256(source).hexdigest()
    index_digest = hashlib.sha256(index).hexdigest()
    bundle_digest = hashlib.sha256(selected_bundle).hexdigest()
    child_digest = hashlib.sha256(selected_child).hexdigest()
    case = case_factory()
    case.update(
        catalog_direct_selection="exact_form_with_lazy_index",
        resolution_schema_version="1",
        screen_kind="html_cover",
        screen_result="unverifiable",
        index_parser_version="index-parser-v1",
        matching_entry_ids_json='["entry_1"]',
        index_response_sha256=index_digest,
        selected_response_sha256=bundle_digest,
        selected_sequence=7,
        selected_retrieval_mode="bundle_sequence",
        selected_url="https://www.sec.gov/selected.zip",
        selected_sha256=child_digest,
        selected_byte_size=len(selected_child),
    )

    append_fixture_case(
        acquisition_paths,
        "fixture_lazy_bundle",
        capture_values,
        case,
        io.BytesIO(source),
        max_response_bytes=1024,
        related_responses={
            "index_response_sha256": io.BytesIO(index),
            "selected_response_sha256": io.BytesIO(selected_bundle),
        },
    )

    assert bundle_digest != child_digest
    with sqlite3.connect(fixture.storage_path) as connection:
        row = connection.execute(
            "SELECT retrieval_mode, sequence, selected_response_sha256, "
            "selected_sequence, selected_retrieval_mode, selected_sha256 "
            "FROM cases"
        ).fetchone()
        assert row == (
            "direct_url",
            None,
            bundle_digest,
            7,
            "bundle_sequence",
            child_digest,
        )
        assert set(
            row[0]
            for row in connection.execute("SELECT response_sha256 FROM response_bodies")
        ) == {source_digest, index_digest, bundle_digest}


def test_ordinary_direct_response_identity_mismatch_is_rejected(
    acquisition_paths, capture_values, case_factory
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_direct_mismatch")
    case = case_factory()
    case.update(selected_sha256="f" * 64, selected_byte_size=999)

    with pytest.raises(FixtureStoreError, match="failed to append"):
        append_fixture_case(
            acquisition_paths,
            "fixture_direct_mismatch",
            capture_values,
            case,
            io.BytesIO(b"ordinary direct response"),
            max_response_bytes=1024,
        )

    with sqlite3.connect(fixture.storage_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM response_bodies").fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


@pytest.mark.parametrize(
    "fault",
    (
        "missing_index",
        "missing_selected",
        "malformed_index",
        "missing_matching_metadata",
        "selected_digest_mismatch",
        "selected_size_mismatch",
    ),
)
def test_lazy_direct_related_evidence_failures_are_atomic(
    acquisition_paths, capture_values, case_factory, fault
) -> None:
    fixture = initialize_fixture(acquisition_paths, f"fixture_lazy_{fault}")
    source = b"initial catalog response"
    index = b"lazy filing index"
    selected = b"selected filing response"
    index_digest = hashlib.sha256(index).hexdigest()
    selected_digest = hashlib.sha256(selected).hexdigest()
    case = case_factory()
    case.update(
        catalog_direct_selection="exact_form_with_lazy_index",
        resolution_schema_version="1",
        screen_kind="html_cover",
        screen_result="unverifiable",
        index_parser_version="index-parser-v1",
        matching_entry_ids_json='["entry_1"]',
        index_response_sha256=index_digest,
        selected_response_sha256=selected_digest,
        selected_retrieval_mode="direct_url",
        selected_url="https://www.sec.gov/selected.htm",
        selected_sha256=(
            "f" * 64 if fault == "selected_digest_mismatch" else selected_digest
        ),
        selected_byte_size=(
            len(selected) + 1 if fault == "selected_size_mismatch" else len(selected)
        ),
    )
    if fault == "missing_matching_metadata":
        case["matching_entry_ids_json"] = None
    related = {}
    if fault != "missing_index":
        related["index_response_sha256"] = io.BytesIO(
            b"malformed index" if fault == "malformed_index" else index
        )
    if fault != "missing_selected":
        related["selected_response_sha256"] = io.BytesIO(selected)

    with pytest.raises(FixtureStoreError):
        append_fixture_case(
            acquisition_paths,
            f"fixture_lazy_{fault}",
            capture_values,
            case,
            io.BytesIO(source),
            max_response_bytes=1024,
            related_responses=related,
        )

    with sqlite3.connect(fixture.storage_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM response_bodies").fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
