"""Offline tests for Phase 2.5 archive fetchers."""

from __future__ import annotations

import hashlib
import importlib
import pickle

import pytest

from defs.filing_identity import full_submission_url_for, parse_archive_url
from defs.sec_http.broker import SecBrokerClient
from defs.sec_http.cache import SqlCache, SqlCacheReader
from defs.sql import QueryCompiler, insert_values, make_sql_executor

fetcher_module = importlib.import_module("phases.025_webpage_storage.core.fetcher")
schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")


def _fixture(path, accession="0001", document_path="index.htm", payload=b"<html>"):
    from defs.sql import ColumnDef, ColumnType, CreateTable, NotNull, PrimaryKey

    path.touch()
    executor = make_sql_executor(path, dialect="sqlite")
    fixture_ddl = CreateTable(
        table=fetcher_module.FIXTURE_PAYLOADS_TABLE,
        columns=(
            ColumnDef("doc_id", ColumnType.TEXT, (PrimaryKey(), NotNull())),
            ColumnDef("raw_payload", ColumnType.BLOB, (NotNull(),)),
        ),
    )
    executor.exec(executor.compiler.compile(fixture_ddl))
    blob_row = {
        "doc_id": schemas.doc_id(accession, document_path),
        "raw_payload": schemas.compress_payload(payload),
    }
    executor.exec(
        QueryCompiler("sqlite").compile(
            insert_values(fetcher_module.FIXTURE_PAYLOADS_TABLE, blob_row)
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


def test_submission_bundle_paths_are_never_stubs():
    # Sequence 000001 accessions end in "0001.txt" but are real bundles.
    assert not fetcher_module.is_stub_document_path("0000950123-98-009115.txt")
    assert not fetcher_module.is_stub_document_path("0000000001-24-000001.txt")
    assert fetcher_module.is_stub_document_path("0001.txt")
    assert fetcher_module.is_stub_document_path("0000.htm")
    assert fetcher_module.is_stub_document_path("")
    assert fetcher_module.is_stub_document_path(None)


def test_live_fetch_fetches_synthetic_bundle_locator_directly():
    sample_sgml = b"""<SUBMISSION>
<DOCUMENT>
<TYPE>10-K
<SEQUENCE>1
<FILENAME>form10k.htm
<TEXT>
<html><body>Pre-2001 Annual Report</body></html>
</TEXT>
</DOCUMENT>
</SUBMISSION>
"""
    called_urls = []

    class Client:
        def get_bytes(self, url):
            called_urls.append(url)
            return sample_sgml

    accession = "000095012398009115"
    bundle_url = full_submission_url_for("20164", accession)
    locator = schemas.DocumentLocator(
        "key",
        accession,
        "0000950123-98-009115.txt",
        bundle_url,
        form="10-K",
        document_path_source="submission_bundle",
    )
    result = fetcher_module.LiveSecArchiveFetcher(Client()).fetch(locator)

    assert result.status == "ok"
    assert b"Pre-2001 Annual Report" in result.payload
    # The synthetic locator is fetched once, directly at the bundle URL.
    assert called_urls == [bundle_url]


def _cache_put(cache: SqlCache, url: str, payload: bytes) -> None:
    cache.put(
        url,
        payload,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        "bytes",
    )


def test_broker_fetcher_serves_cached_hit_without_broker(tmp_path):
    payload = b"<html><body>Primary Document</body></html>"
    url = "https://www.sec.gov/Archives/edgar/data/1/0000000001-000001.htm"
    _cache_put(SqlCache(tmp_path / "cache"), url, payload)

    fetcher = fetcher_module.BrokerArchiveFetcher(
        SecBrokerClient(tmp_path / "missing.sock"),
        cache_reader=SqlCacheReader(tmp_path / "cache"),
    )
    locator = schemas.DocumentLocator("key", "0000000001000001", "doc.htm", url)

    result = fetcher.fetch(locator)

    assert result.status == "ok"
    assert result.payload == payload


def test_cached_hit_skips_broker_rpc(tmp_path):
    payload = b"<html><body>Primary Document</body></html>"
    url = "https://www.sec.gov/Archives/edgar/data/1/0000000001-000001.htm"
    _cache_put(SqlCache(tmp_path / "cache"), url, payload)

    class CountingBroker:
        def __init__(self):
            self.calls = []

        def fetch(self, url):
            self.calls.append(url)
            return {"status": "failed", "error": "must not be called"}

    broker = CountingBroker()
    fetcher = fetcher_module.BrokerArchiveFetcher(
        broker, cache_reader=SqlCacheReader(tmp_path / "cache")
    )
    locator = schemas.DocumentLocator("key", "0000000001000001", "doc.htm", url)

    result = fetcher.fetch(locator)

    assert result.status == "ok"
    assert result.payload == payload
    assert broker.calls == []


def test_broker_fetcher_serves_cached_full_submission_fallback(tmp_path):
    sample_sgml = (
        b"<SUBMISSION><DOCUMENT><TYPE>10-K<SEQUENCE>1<FILENAME>form10k.htm"
        b"<TEXT><html><body>Substantive 10-K Content</body></html></TEXT>"
        b"</DOCUMENT></SUBMISSION>"
    )
    url = (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/missing.htm"
    )
    parts = parse_archive_url(url)
    full_sub_url = full_submission_url_for(parts.archive_cik, "000032019320000096")
    cache = SqlCache(tmp_path / "cache")
    _cache_put(cache, full_sub_url, sample_sgml)

    fetcher = fetcher_module.BrokerArchiveFetcher(
        SecBrokerClient(tmp_path / "missing.sock"),
        cache_reader=SqlCacheReader(tmp_path / "cache"),
    )
    locator = schemas.DocumentLocator(
        "key",
        "000032019320000096",
        "missing.htm",
        url,
        form="10-K",
    )

    result = fetcher.fetch(locator)

    assert result.status == "ok"
    assert b"Substantive 10-K Content" in result.payload


def test_broker_fetcher_miss_with_dead_broker_fails_cleanly(tmp_path):
    fetcher = fetcher_module.BrokerArchiveFetcher(
        SecBrokerClient(tmp_path / "missing.sock"),
        cache_reader=SqlCacheReader(tmp_path / "empty-cache"),
    )
    locator = schemas.DocumentLocator(
        "key",
        "0000000001000001",
        "doc.htm",
        "https://www.sec.gov/Archives/edgar/data/1/0000000001-000001.htm",
    )

    result = fetcher.fetch(locator)

    assert result.status == "failed"
    assert result.error
    assert result.payload is None


def test_broker_fetcher_pickle_round_trip_preserves_cache_reader(tmp_path):
    payload = b"<html><body>Primary Document</body></html>"
    url = "https://www.sec.gov/Archives/edgar/data/1/0000000001-000001.htm"
    _cache_put(SqlCache(tmp_path / "cache"), url, payload)

    fetcher = fetcher_module.BrokerArchiveFetcher(
        SecBrokerClient(tmp_path / "broker.sock"),
        cache_reader=SqlCacheReader(tmp_path / "cache"),
    )
    restored = pickle.loads(pickle.dumps(fetcher))
    locator = schemas.DocumentLocator("key", "0000000001000001", "doc.htm", url)

    assert restored._cache is not None
    result = restored.fetch(locator)

    assert result.status == "ok"
    assert result.payload == payload


def test_make_archive_fetcher_wires_cache_reader(tmp_path):
    fetcher = fetcher_module.make_archive_fetcher(
        "production",
        broker_socket=tmp_path / "broker.sock",
        cache_dir=tmp_path / "cache",
    )
    plain = fetcher_module.make_archive_fetcher(
        "production", broker_socket=tmp_path / "broker.sock"
    )

    assert isinstance(fetcher, fetcher_module.BrokerArchiveFetcher)
    assert fetcher._cache is not None
    assert plain._cache is None


def _pem_wrapped(inner: bytes) -> bytes:
    return (
        b"-----BEGIN PRIVACY-ENHANCED MESSAGE-----\n"
        b"Proc-Type: 2001,MIC-CLEAR\n"
        b"Originator-Name: webmaster@www.sec.gov\n"
        b"MIC-Info: RSA-MD5,RSA,\n"
        b" abc==\n"
        b"\n" + inner + b"-----END PRIVACY-ENHANCED MESSAGE-----\n"
    )


_PEM_BUNDLE = _pem_wrapped(
    b"<SEC-DOCUMENT>0000947716-97-000009.txt : 19970313\n"
    b"<SEC-HEADER>0000947716-97-000009.hdr.sgml : 19970313\n"
    + b"COMPANY CONFORMED NAME: PADDED HEADER LINE\n"
    * 40
    + b"</SEC-HEADER>\n"
    b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>1\n<FILENAME>10k.txt\n<TEXT>\n"
    b"PRIMARY 10-K BODY\n"
    b"</TEXT>\n</DOCUMENT>\n"
    b"<DOCUMENT>\n<TYPE>EX-13\n<SEQUENCE>2\n<FILENAME>ex13.txt\n<TEXT>\n"
    b"EXHIBIT 13 BODY\n"
    b"</TEXT>\n</DOCUMENT>\n"
    b"</SEC-DOCUMENT>\n"
)


def _extract(payload: bytes, form: str, path: str):
    locator = schemas.DocumentLocator("k", "0000947716-97-000009", path, "", form)
    return fetcher_module.extract_from_sgml_envelope(payload, locator)


def test_extract_from_sgml_envelope_pem_wrapped_bundle():
    # PEM headers push <DOCUMENT> past byte 1000; the old head-guard failed here.
    assert b"<DOCUMENT>" not in _PEM_BUNDLE[:1000]
    payload, source_bundle = _extract(_PEM_BUNDLE, "10-K", "0000947716-97-000009.txt")
    assert payload == b"PRIMARY 10-K BODY"
    assert source_bundle is not None
    assert b"<TYPE>EX-13" in source_bundle


def test_extract_from_sgml_envelope_plain_payload_unchanged():
    raw = b"<html><body>plain document</body></html>"
    payload, source_bundle = _extract(raw, "10-K", "doc.htm")
    assert payload == raw
    assert source_bundle is None


def test_locate_sub_document_in_bundle_resolves_exhibit():
    _, bundle = _extract(_PEM_BUNDLE, "10-K", "0000947716-97-000009.txt")
    exhibit = fetcher_module.locate_sub_document_in_bundle(bundle, ("EX-13",), None)
    assert exhibit == b"EXHIBIT 13 BODY"
