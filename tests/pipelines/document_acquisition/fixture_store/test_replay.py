import hashlib
import io
import sqlite3

import pytest
import zstandard

from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.replay import (
    replay_fixture_response,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.storage import (
    append_fixture_case,
    initialize_fixture,
)


def test_direct_response_replays_exact_bytes(
    acquisition_paths, capture_values, case_factory
) -> None:
    initialize_fixture(acquisition_paths, "fixture_replay")
    response = b"<html>original response</html>\x00"
    body = append_fixture_case(
        acquisition_paths,
        "fixture_replay",
        capture_values,
        case_factory(),
        io.BytesIO(response),
        max_response_bytes=len(response),
    )
    assert body is not None

    output = io.BytesIO()
    replayed = replay_fixture_response(
        acquisition_paths, "fixture_replay", body.response_sha256, output
    )
    assert replayed.byte_size == len(response)
    assert output.getvalue() == response


def test_replay_rejects_body_with_changed_uncompressed_identity(
    acquisition_paths, capture_values, case_factory
) -> None:
    fixture = initialize_fixture(acquisition_paths, "fixture_corrupt")
    response = b"original-body"
    body = append_fixture_case(
        acquisition_paths,
        "fixture_corrupt",
        capture_values,
        case_factory(),
        io.BytesIO(response),
        max_response_bytes=len(response),
    )
    assert body is not None
    forged = b"replaced-body"
    compressed = zstandard.ZstdCompressor().compress(forged)
    assert len(compressed) == body.stored_byte_size
    with sqlite3.connect(fixture.storage_path) as connection:
        connection.execute("DROP TRIGGER immutable_response_update")
        connection.execute(
            "CREATE TRIGGER immutable_response_update AFTER UPDATE ON response_bodies "
            "BEGIN SELECT 1; END"
        )
        connection.execute(
            "UPDATE response_bodies SET stored_sha256 = ?, compressed_body = ? "
            "WHERE response_sha256 = ?",
            (hashlib.sha256(compressed).hexdigest(), compressed, body.response_sha256),
        )

    with pytest.raises(FixtureStoreError, match="response size or SHA-256 mismatch"):
        replay_fixture_response(
            acquisition_paths,
            "fixture_corrupt",
            body.response_sha256,
            io.BytesIO(),
        )
