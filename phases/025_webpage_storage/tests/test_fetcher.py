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


def test_live_fetch_falls_back_to_full_sgml_on_failure():
    sample_sgml = b"""<SUBMISSION>
<DOCUMENT>
<TYPE>10-K
<SEQUENCE>1
<FILENAME>form10k.htm
<TEXT>
<html><body>Substantive 10-K Content</body></html>
</TEXT>
</DOCUMENT>
</SUBMISSION>
"""
    called_urls = []

    class Client:
        def get_bytes(self, url):
            called_urls.append(url)
            if "form10k_missing.htm" in url:
                raise RuntimeError("404 Not Found")
            if "0000320193-20-000096.txt" in url:
                return sample_sgml
            raise RuntimeError("Unexpected URL")

    locator = schemas.DocumentLocator(
        "key",
        "000032019320000096",
        "form10k_missing.htm",
        "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/form10k_missing.htm",
        form="10-K",
    )
    result = fetcher_module.LiveSecArchiveFetcher(Client()).fetch(locator)

    assert result.status == "ok"
    assert b"Substantive 10-K Content" in result.payload
    assert len(called_urls) == 2


def test_live_fetch_direct_stub_routes_directly_to_full_sgml():
    sample_sgml = b"""<SUBMISSION>
<DOCUMENT>
<TYPE>20-F
<SEQUENCE>1
<FILENAME>f20f.htm
<TEXT>
<html><body>20-F Foreign Report</body></html>
</TEXT>
</DOCUMENT>
</SUBMISSION>
"""
    called_urls = []

    class Client:
        def get_bytes(self, url):
            called_urls.append(url)
            if "0000320193-20-000096.txt" in url:
                return sample_sgml
            raise RuntimeError(f"Unexpected URL: {url}")

    locator = schemas.DocumentLocator(
        "key",
        "000032019320000096",
        "0001.txt",
        "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/0001.txt",
        form="20-F",
    )
    result = fetcher_module.LiveSecArchiveFetcher(Client()).fetch(locator)

    assert result.status == "ok"
    assert b"20-F Foreign Report" in result.payload
    assert len(called_urls) == 1
    assert "0000320193-20-000096.txt" in called_urls[0]


def test_broker_fetch_falls_back_to_full_sgml():
    sample_sgml = b"""<SUBMISSION>
<DOCUMENT>
<TYPE>8-K
<SEQUENCE>1
<FILENAME>currentevent.htm
<TEXT>Item 1.01 Entry into Agreement</TEXT>
</DOCUMENT>
</SUBMISSION>
"""

    class Broker:
        def fetch(self, url):
            if "missing_8k.htm" in url:
                return {"status": "failed", "error": "HTTP 404"}
            if "0000320193-20-000096.txt" in url:
                return {"status": "ok", "payload": sample_sgml}
            return {"status": "failed", "error": "unknown"}

    locator = schemas.DocumentLocator(
        "key",
        "000032019320000096",
        "missing_8k.htm",
        "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/missing_8k.htm",
        form="8-K",
    )
    result = fetcher_module.BrokerArchiveFetcher(Broker()).fetch(locator)

    assert result.status == "ok"
    assert b"Item 1.01" in result.payload


def test_factory_validates_mode_dependencies():
    with pytest.raises(ValueError, match="fixture_paths"):
        fetcher_module.make_archive_fetcher("fixture")
    with pytest.raises(ValueError, match="http_client"):
        fetcher_module.make_archive_fetcher("live")
    with pytest.raises(ValueError, match="unsupported"):
        fetcher_module.make_archive_fetcher("other")
