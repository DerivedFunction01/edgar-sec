"""Tests for the archive fetcher seam."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from edgar_sec.domain.document.models import DocumentLocator
from edgar_sec.infra.storage.fixture_store import FixtureStore
from edgar_sec.pipelines.document_storage.fetching import (
    ArchiveFetcher,
    BrokerArchiveFetcher,
    FixtureArchiveFetcher,
    LiveArchiveFetcher,
    build_broker_fetcher,
    extract_from_sgml_envelope,
    make_archive_fetcher,
)

ACCESSION = "0001234567-11-000001"
ARCHIVE_URL = (
    "https://www.sec.gov/Archives/edgar/data/1234567/000123456711000001/acme-10k.htm"
)

SGML_BUNDLE = (
    b"<SEC-DOCUMENT><SEC-HEADER>0001</SEC-HEADER><TYPE>10-K</TYPE>"
    b"<FILENAME>acme-10k.htm</FILENAME><DOCUMENT><TYPE>10-K</TYPE>"
    b"<SEQUENCE>1</SEQUENCE><FILENAME>acme-10k.htm</FILENAME><TEXT>\n"
    b"<HTML><BODY>PRIMARY DOCUMENT BODY</BODY></HTML>\n"
    b"</TEXT></DOCUMENT></SEC-DOCUMENT>"
)


def _locator(
    document_path: str = "acme-10k.htm", form: str = "10-K"
) -> DocumentLocator:
    return DocumentLocator.from_parts(
        ACCESSION, document_path, archive_url=ARCHIVE_URL, form=form
    )


class FakeHttpClient:
    """Transport-seam fake: maps URL suffix to bytes or an error."""

    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []
        self.user_agent = "test-agent"
        self.cache_dir = None
        self.metrics = object()

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        for suffix, response in self.responses.items():
            if url.endswith(suffix):
                if isinstance(response, Exception):
                    raise response
                return response
        raise KeyError(f"no fake response for {url}")


class FakeBroker:
    def __init__(self, responses: dict[str, bytes | str]) -> None:
        self.responses = responses
        self.calls: list[str] = []
        self.socket_path = "/tmp/fake-broker.sock"
        self.metrics = None

    def fetch(self, url: str) -> dict[str, object]:
        self.calls.append(url)
        for suffix, response in self.responses.items():
            if url.endswith(suffix):
                if isinstance(response, str):
                    return {"status": "failed", "error": response, "payload": None}
                return {"status": "ok", "error": None, "payload": response}
        return {"status": "failed", "error": "no fake response", "payload": None}


class FakeCacheReader:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.cache_dir = Path("/tmp/fake-cache")

    def get(self, url: str) -> bytes | None:
        for suffix, payload in self.payloads.items():
            if url.endswith(suffix):
                return payload
        return None


# --- SGML envelope selection ---------------------------------------------


def test_plain_document_is_returned_unchanged() -> None:
    payload = b"<html><body>plain</body></html>"
    extracted, source = extract_from_sgml_envelope(payload, _locator())
    assert extracted == payload
    assert source is None


def test_envelope_selects_the_target_sub_document() -> None:
    extracted, source = extract_from_sgml_envelope(SGML_BUNDLE, _locator())
    assert extracted is not None
    assert b"PRIMARY DOCUMENT BODY" in extracted
    assert b"<SEC-DOCUMENT>" not in extracted
    assert source == SGML_BUNDLE


def test_empty_payload_extracts_to_nothing() -> None:
    assert extract_from_sgml_envelope(b"", _locator()) == (None, None)


def test_pem_envelope_is_unwrapped_before_scanning() -> None:
    pem = (
        b"-----BEGIN PRIVACY-ENHANCED MESSAGE-----\n"
        b"Proc-Type: ENCRYPTED\n\n"
        + SGML_BUNDLE
        + b"\n-----END PRIVACY-ENHANCED MESSAGE-----\n"
    )
    extracted, source = extract_from_sgml_envelope(pem, _locator())
    assert extracted is not None
    assert b"PRIMARY DOCUMENT BODY" in extracted
    assert source is not None


def test_single_document_bundle_resolves_to_that_document() -> None:
    """A bundle holding one exhibit resolves to it rather than yielding nothing.

    The unpacker falls back to the first available sub-document, so a
    single-document bundle is always resolvable; that is what makes a
    stub-path locator work against an exhibit-only bundle.
    """
    bundle = (
        b"<SEC-DOCUMENT><DOCUMENT><TYPE>EX-99.1</TYPE><SEQUENCE>2</SEQUENCE>"
        b"<FILENAME>other.htm</FILENAME><TEXT><html>exhibit</html></TEXT>"
        b"</DOCUMENT></SEC-DOCUMENT>"
    )
    extracted, source = extract_from_sgml_envelope(bundle, _locator())
    assert extracted == b"<html>exhibit</html>"
    assert source == bundle


# --- fixture fetcher ------------------------------------------------------


def _seed_fixture(db_path: Path, locator: DocumentLocator, payload: bytes) -> None:
    with FixtureStore(db_path) as store:
        store.put_many([(locator.document_locator_key, payload)])


def test_fixture_fetcher_returns_stored_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "fix.sqlite"
    locator = _locator()
    _seed_fixture(db_path, locator, b"<html>stored</html>")
    fetcher = FixtureArchiveFetcher([db_path])
    result = fetcher.fetch(locator)
    assert result.ok is True
    assert result.payload == b"<html>stored</html>"
    assert result.status == "ok"
    fetcher.close()


def test_fixture_fetcher_reports_missing(tmp_path: Path) -> None:
    fetcher = FixtureArchiveFetcher([tmp_path / "fix.sqlite"])
    result = fetcher.fetch(_locator())
    assert result.status == "missing"
    assert result.payload is None
    assert result.ok is False
    fetcher.close()


def test_fixture_fetcher_selects_from_a_stored_bundle(tmp_path: Path) -> None:
    """A bundle stored under the accession resolves a sub-document locator."""
    from edgar_sec.domain.sec_urls import accession_hyphenated

    db_path = tmp_path / "fix.sqlite"
    bundle_locator = DocumentLocator.from_parts(
        ACCESSION,
        f"{accession_hyphenated(ACCESSION)}.txt",
        archive_url=ARCHIVE_URL,
    )
    _seed_fixture(db_path, bundle_locator, SGML_BUNDLE)
    fetcher = FixtureArchiveFetcher([db_path])
    result = fetcher.fetch(_locator())
    assert result.ok is True
    assert b"PRIMARY DOCUMENT BODY" in result.payload
    assert result.source_payload == SGML_BUNDLE
    fetcher.close()


def test_fixture_fetcher_checks_fixtures_in_order(tmp_path: Path) -> None:
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"
    locator = _locator()
    _seed_fixture(second, locator, b"<html>second</html>")
    fetcher = FixtureArchiveFetcher([first, second])
    assert fetcher.fetch(locator).payload == b"<html>second</html>"
    fetcher.close()


def test_fixture_fetcher_is_picklable(tmp_path: Path) -> None:
    """The fetcher must survive the process-pool boundary it is shipped over."""
    db_path = tmp_path / "fix.sqlite"
    locator = _locator()
    _seed_fixture(db_path, locator, b"<html>pickled</html>")
    fetcher = FixtureArchiveFetcher([db_path])
    restored = pickle.loads(pickle.dumps(fetcher))
    assert restored.fetch(locator).payload == b"<html>pickled</html>"
    fetcher.close()
    restored.close()


def test_fixture_fetcher_reports_failure_not_exception(tmp_path: Path) -> None:
    """A corrupt fixture becomes a failed status, never a raised exception."""
    db_path = tmp_path / "corrupt.sqlite"
    db_path.write_bytes(b"not a database")
    fetcher = FixtureArchiveFetcher([db_path])
    result = fetcher.fetch(_locator())
    assert result.status in {"failed", "missing"}
    assert result.payload is None
    fetcher.close()


def test_fixture_fetcher_ignores_absent_files(tmp_path: Path) -> None:
    fetcher = FixtureArchiveFetcher([tmp_path / "nope.sqlite"])
    assert fetcher.fetch(_locator()).status == "missing"
    fetcher.close()


# --- broker fetcher -------------------------------------------------------


def test_broker_fetcher_fetches_the_direct_url() -> None:
    broker = FakeBroker({"acme-10k.htm": b"<html>broker</html>"})
    result = BrokerArchiveFetcher(broker).fetch(_locator())
    assert result.ok is True
    assert result.payload == b"<html>broker</html>"
    assert len(broker.calls) == 1


def test_broker_fetcher_falls_back_to_the_submission_bundle() -> None:
    broker = FakeBroker({".txt": SGML_BUNDLE})
    result = BrokerArchiveFetcher(broker).fetch(_locator())
    assert result.ok is True
    assert b"PRIMARY DOCUMENT BODY" in result.payload
    assert len(broker.calls) == 2


def test_broker_fetcher_skips_the_direct_url_for_a_stub() -> None:
    broker = FakeBroker({"0001.txt": SGML_BUNDLE, "0001.htm": b"<html>stub</html>"})
    result = BrokerArchiveFetcher(
        broker,
    ).fetch(_locator("acme-10k-0001.htm"))
    assert result.ok is True
    assert b"PRIMARY DOCUMENT BODY" in result.payload


def test_broker_fetcher_probes_the_cache_first() -> None:
    broker = FakeBroker({"acme-10k.htm": b"<html>from broker</html>"})
    cache = FakeCacheReader({"acme-10k.htm": b"<html>from cache</html>"})
    result = BrokerArchiveFetcher(broker, cache_reader=cache).fetch(_locator())
    assert result.payload == b"<html>from cache</html>"
    assert broker.calls == []


def test_broker_fetcher_only_misses_reach_the_socket() -> None:
    broker = FakeBroker({"acme-10k.htm": b"<html>from broker</html>"})
    cache = FakeCacheReader({"other.htm": b"<html>irrelevant</html>"})
    result = BrokerArchiveFetcher(broker, cache_reader=cache).fetch(_locator())
    assert result.payload == b"<html>from broker</html>"
    assert broker.calls == [ARCHIVE_URL]


def test_broker_fetcher_reports_failure() -> None:
    broker = FakeBroker({"acme-10k.htm": "rate limited", ".txt": "rate limited"})
    result = BrokerArchiveFetcher(broker).fetch(_locator())
    assert result.status == "failed"
    assert result.error


def test_broker_fetcher_survives_a_transport_exception() -> None:
    class ExplodingBroker:
        socket_path = "/tmp/exploding.sock"
        metrics = None

        def fetch(self, url: str) -> dict[str, object]:
            raise OSError("socket closed")

    result = BrokerArchiveFetcher(ExplodingBroker()).fetch(_locator())
    assert result.status == "failed"
    assert "socket closed" in (result.error or "")


def test_broker_fetcher_without_a_socket_reports_failure() -> None:
    fetcher = BrokerArchiveFetcher(None)
    result = fetcher.fetch(_locator())
    assert result.status == "failed"
    assert "socket" in (result.error or "")


def test_broker_fetcher_pickles_its_socket_path() -> None:
    """Unpickling rebuilds a real socket client, so only the identity travels."""
    broker = FakeBroker({"acme-10k.htm": b"<html>x</html>"})
    restored = pickle.loads(pickle.dumps(BrokerArchiveFetcher(broker)))
    assert str(restored._broker.socket_path) == broker.socket_path


# --- live fetcher ---------------------------------------------------------


def test_live_fetcher_uses_the_injected_client() -> None:
    client = FakeHttpClient({"acme-10k.htm": b"<html>live</html>"})
    result = LiveArchiveFetcher(client).fetch(_locator())
    assert result.ok is True
    assert result.payload == b"<html>live</html>"
    assert client.calls == [ARCHIVE_URL]


def test_live_fetcher_falls_back_to_the_bundle() -> None:
    client = FakeHttpClient({".txt": SGML_BUNDLE})
    result = LiveArchiveFetcher(client).fetch(_locator())
    assert result.ok is True
    assert b"PRIMARY DOCUMENT BODY" in result.payload
    assert len(client.calls) == 2


def test_live_fetcher_reports_failure_when_everything_fails() -> None:
    client = FakeHttpClient({})
    result = LiveArchiveFetcher(client).fetch(_locator())
    assert result.status == "failed"
    assert result.error


def test_live_fetcher_resolves_an_exhibit_only_bundle() -> None:
    """Any resolvable bundle is an ok result, never a silent empty payload."""
    client = FakeHttpClient(
        {
            ".txt": b"<SEC-DOCUMENT><DOCUMENT><TYPE>EX-99.1</TYPE>"
            b"<TEXT><html>press release</html></TEXT></DOCUMENT></SEC-DOCUMENT>"
        }
    )
    result = LiveArchiveFetcher(client).fetch(_locator())
    assert result.ok is True
    assert result.payload == b"<html>press release</html>"


def test_live_fetcher_exposes_metrics() -> None:
    client = FakeHttpClient({"acme-10k.htm": b"<html>x</html>"})
    assert LiveArchiveFetcher(client).metrics is client.metrics


# --- factory --------------------------------------------------------------


def test_factory_builds_the_fixture_fetcher(tmp_path: Path) -> None:
    fetcher = make_archive_fetcher("fixture", db_paths=[tmp_path / "f.sqlite"])
    assert isinstance(fetcher, FixtureArchiveFetcher)
    fetcher.close()


def test_fixture_mode_requires_paths() -> None:
    with pytest.raises(ValueError, match="db_paths"):
        make_archive_fetcher("fixture")


def test_factory_builds_the_live_fetcher() -> None:
    client = FakeHttpClient({"acme-10k.htm": b"<html>live</html>"})
    fetcher = make_archive_fetcher("live", http_client=client)
    assert isinstance(fetcher, LiveArchiveFetcher)


def test_live_mode_requires_a_client() -> None:
    with pytest.raises(ValueError, match="http_client"):
        make_archive_fetcher("live")


def test_factory_builds_the_broker_fetcher() -> None:
    fetcher = make_archive_fetcher("broker", broker_socket="/tmp/b.sock")
    assert isinstance(fetcher, BrokerArchiveFetcher)


def test_build_broker_fetcher_accepts_a_cache_reader() -> None:
    reader = FakeCacheReader({"acme-10k.htm": b"<html>cached</html>"})
    fetcher = build_broker_fetcher("/tmp/b.sock", cache_reader=reader)
    assert isinstance(fetcher, BrokerArchiveFetcher)
    assert fetcher._cache is reader
    assert fetcher._cache_dir == reader.cache_dir


def test_build_broker_fetcher_without_a_cache_reader() -> None:
    fetcher = build_broker_fetcher("/tmp/b.sock")
    assert fetcher._cache is None


def test_unsupported_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        make_archive_fetcher("carrier-pigeon")


def test_mode_is_normalized() -> None:
    fetcher = make_archive_fetcher(
        "  FIXTURE ", db_paths=["/tmp/does-not-exist.sqlite"]
    )
    assert isinstance(fetcher, FixtureArchiveFetcher)
    fetcher.close()


@pytest.mark.parametrize(
    "fetcher",
    [
        FixtureArchiveFetcher(["/tmp/none.sqlite"]),
        BrokerArchiveFetcher(FakeBroker({})),
        LiveArchiveFetcher(FakeHttpClient({})),
    ],
)
def test_every_backend_satisfies_the_protocol(fetcher: object) -> None:
    assert isinstance(fetcher, ArchiveFetcher)
