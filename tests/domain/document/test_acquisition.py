"""Tests for document acquisition domain records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from edgar_sec.domain.document.acquisition import (
    AcquisitionFailure,
    FetchResult,
    is_stub_document_path,
)
from edgar_sec.domain.document.models import (
    DocumentLocator,
    derive_document_locator_key,
)

LOCATOR = DocumentLocator.from_parts(
    "0001234567-11-000001",
    "acme-10k.htm",
    archive_url="https://www.sec.gov/Archives/edgar/data/1234567/x/acme-10k.htm",
    form="10-K",
    source_cik="1234567",
)


def test_locator_key_is_derived_not_supplied() -> None:
    same = DocumentLocator.from_parts(
        "0001234567-11-000001", "acme-10k.htm", archive_url="https://other"
    )
    assert LOCATOR.document_locator_key == same.document_locator_key
    assert LOCATOR.document_locator_key == derive_document_locator_key(
        "0001234567-11-000001", "acme-10k.htm"
    )


def test_locator_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        LOCATOR.accession = "other"  # type: ignore[misc]


def test_locator_exposes_stub_state() -> None:
    assert LOCATOR.is_stub_path is False
    stub = DocumentLocator.from_parts(
        "0001234567-11-000001", "acme-10k-0001.htm", archive_url="u"
    )
    assert stub.is_stub_path is True


def test_fetch_result_ok_requires_payload() -> None:
    assert FetchResult(LOCATOR, b"x", "ok").ok is True
    assert FetchResult(LOCATOR, None, "ok").ok is False
    assert FetchResult(LOCATOR, b"x", "missing").ok is False
    assert FetchResult(LOCATOR, b"x", "failed").ok is False


def test_fetch_result_byte_size() -> None:
    assert FetchResult(LOCATOR, b"12345", "ok").byte_size == 5
    assert FetchResult(LOCATOR, None, "failed").byte_size == 0


def test_fetch_result_carries_the_source_bundle() -> None:
    result = FetchResult(LOCATOR, b"body", "ok", source_payload=b"bundle")
    assert result.source_payload == b"bundle"
    assert result.error is None


def test_acquisition_failure_defaults() -> None:
    failure = AcquisitionFailure(
        document_locator_key="k", accession="a", document_path="p", error="boom"
    )
    assert failure.status == "failed"
    assert failure.metadata == {}


@pytest.mark.parametrize(
    "path",
    ["", None, "acme-10k-0001.htm", "acme-10k-0001.txt", "x-0000.htm", "x-0000.txt"],
)
def test_stub_paths(path: str | None) -> None:
    assert is_stub_document_path(path) is True


@pytest.mark.parametrize(
    "path",
    ["acme-10k.htm", "0001234567-11-000001.txt", "xslF345X02/doc3.xml"],
)
def test_non_stub_paths(path: str) -> None:
    assert is_stub_document_path(path) is False
