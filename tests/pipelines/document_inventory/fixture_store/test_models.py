from __future__ import annotations

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    CapturedIndexPage,
    IndexCaptureFailure,
    IndexResponseKey,
    SCHEMA_VERSION,
)


def test_response_keys_are_value_records() -> None:
    first = IndexResponseKey("https://example.test/index", "a" * 64)
    assert first == IndexResponseKey(first.request_url, first.response_sha256)
    assert hash(first) == hash(
        IndexResponseKey(first.request_url, first.response_sha256)
    )


def test_page_contains_exact_response_body() -> None:
    body = b"response bytes"
    page = CapturedIndexPage(
        accession=AccessionNumber("0000123456-12-000001"),
        key=IndexResponseKey("https://example.test/index", "a" * 64),
        body=body,
        captured_at="2024-01-01T00:00:00+00:00",
    )
    assert page.body == body
    assert page.byte_size == len(body)
    with pytest.raises(AttributeError):
        page.body = b"changed"  # type: ignore[misc]


def test_capture_failure_is_immutable() -> None:
    failure = IndexCaptureFailure(
        AccessionNumber("0000123456-12-000001"), "http_error", "not found"
    )
    assert failure.raw_broker_error == "not found"
    with pytest.raises(AttributeError):
        failure.failure_code = "changed"  # type: ignore[misc]


def test_schema_version_is_explicit() -> None:
    assert SCHEMA_VERSION == 2
