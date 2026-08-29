"""Offline tests for Phase 2.5 archive fetchers."""

from __future__ import annotations

import importlib

import pytest

from defs.sql import QueryCompiler, insert_values, make_sql_executor

fetcher_module = importlib.import_module("phases.025_webpage_storage.core.fetcher")
schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")


def _fixture(path, accession="0001", document_path="index.htm", payload=b"<html>"):
    path.touch()
    executor = make_sql_executor(path, dialect="sqlite")
    schemas.create_chunk_schema(executor)
    blob = schemas.build_blob(accession, document_path, payload)
    executor.exec(
        QueryCompiler("sqlite").compile(
            insert_values(schemas.DOCUMENT_BLOBS_TABLE, blob.to_row())
        )
    )
    executor.backend.connection.commit()
    executor.close()


def test_fixture_fetch_decompresses_blob(tmp_path):
    path = tmp_path / "fixture.sqlite"
    _fixture(path)
    locator = schemas.DocumentLocator("key", "0001", "index.htm", "unused")

    result = fetcher_module.FixtureArchiveFetcher([path]).fetch(locator)

    assert result.status == "ok"
    assert result.payload == b"<html>"


def test_fixture_fetch_missing_is_not_an_error(tmp_path):
    path = tmp_path / "fixture.sqlite"
    _fixture(path)
    locator = schemas.DocumentLocator("key", "0001", "missing.htm", "unused")

    result = fetcher_module.FixtureArchiveFetcher([path]).fetch(locator)

    assert result.status == "missing"
    assert result.payload is None
    assert result.error is None


def test_live_fetch_uses_injected_client():
    class Client:
        def get_bytes(self, url):
            assert url == "https://example.test/doc.htm"
            return b"raw"

    locator = schemas.DocumentLocator(
        "key", "0001", "doc.htm", "https://example.test/doc.htm"
    )
    result = fetcher_module.LiveSecArchiveFetcher(Client()).fetch(locator)

    assert result.status == "ok"
    assert result.payload == b"raw"


def test_factory_validates_mode_dependencies():
    with pytest.raises(ValueError, match="fixture_paths"):
        fetcher_module.make_archive_fetcher("fixture")
    with pytest.raises(ValueError, match="http_client"):
        fetcher_module.make_archive_fetcher("live")
    with pytest.raises(ValueError, match="unsupported"):
        fetcher_module.make_archive_fetcher("other")
