from __future__ import annotations

import io

import pytest

from edgar_sec.pipelines.document_acquisition.fixture_store.body_verification import (
    _verify_body_row,
    _write_verified_body,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.models import (
    FixtureStoreError,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.schema import (
    connect,
    fixture_paths,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from tests.pipelines.document_acquisition.fixture_store.fixture_helpers import (
    append_test_case,
    initialize_test_fixture,
)


def test_verified_body_writer_reconstructs_exact_bytes(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    body = b"selected parser body\n" * 30
    append_test_case(paths, "fixture-a", "target-a", body)

    output = io.BytesIO()
    ref = _write_verified_body(
        paths,
        "fixture-a",
        append_test_case(paths, "fixture-a", "target-a", body).body_sha256,
        output,
    )

    assert ref.byte_size == len(body)
    assert output.getvalue() == body


def test_body_verifier_rejects_corrupted_stored_digest(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    append_test_case(paths, "fixture-a", "target-a", b"fixture body")
    fixture = fixture_paths(paths, "fixture-a")
    connection = connect(fixture.storage_path)
    try:
        connection.execute("DROP TRIGGER immutable_body_blob_update")
        connection.execute("UPDATE body_blobs SET stored_sha256 = ?", ("0" * 64,))
        row = connection.execute(
            "SELECT body_id, body_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size "
            "FROM body_blobs"
        ).fetchone()
        with pytest.raises(
            FixtureStoreError, match="stored body size or SHA-256 mismatch"
        ):
            _verify_body_row(connection, row)
    finally:
        connection.close()


def test_body_verifier_rejects_truncated_compressed_blob(tmp_path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    initialize_test_fixture(paths, "fixture-a")
    append_test_case(paths, "fixture-a", "target-a", b"fixture body")
    fixture = fixture_paths(paths, "fixture-a")
    connection = connect(fixture.storage_path)
    try:
        connection.execute("DROP TRIGGER immutable_body_blob_update")
        connection.execute(
            "UPDATE body_blobs SET compressed_body = zeroblob(stored_byte_size)"
        )
        row = connection.execute(
            "SELECT body_id, body_sha256, byte_size, storage_codec, stored_sha256, stored_byte_size "
            "FROM body_blobs"
        ).fetchone()
        with pytest.raises(FixtureStoreError, match="invalid Zstandard fixture body"):
            _verify_body_row(connection, row)
    finally:
        connection.close()
