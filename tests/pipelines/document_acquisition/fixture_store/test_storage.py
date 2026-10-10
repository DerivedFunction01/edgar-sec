import hashlib
import io
import sqlite3

import pytest

from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import CHUNK_SIZE
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
    source = BoundedSource(b"x" * (CHUNK_SIZE * 5 + 13))
    append_fixture_case(
        acquisition_paths,
        "fixture_bounded",
        capture_values,
        case_factory(),
        source,
        max_response_bytes=CHUNK_SIZE * 6,
    )
    assert 0 < source.maximum_read <= CHUNK_SIZE


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
