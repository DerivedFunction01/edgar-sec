from __future__ import annotations

import pickle
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.document.acquisition import (
    AcquisitionSourceKind,
    SubmissionFormat,
)
from edgar_sec.domain.document.models import (
    DocumentLocator,
    FilingOccurrence,
    derive_document_locator_key,
)
from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.identity import Cik
from edgar_sec.domain.sec_urls import accession_hyphenated
from edgar_sec.pipelines.document_storage.fetching import (
    ArchiveFetcher,
    BrokerArchiveFetcher,
    FixtureArchiveFetcher,
    LiveArchiveFetcher,
    archive_root_url,
    build_broker_fetcher,
    extract_from_sgml_envelope,
    make_archive_fetcher,
    _submission_targets,
)
from edgar_sec.pipelines.document_storage.fixture_store import FixtureStore
from edgar_sec.pipelines.document_storage.processor import PassThroughProcessor
from edgar_sec.pipelines.document_storage.execution import process_chunk

ACCESSION = "0001234567-11-000001"
ARCHIVE_URL = (
    "https://www.sec.gov/Archives/edgar/data/1234567/000123456711000001/acme-10k.htm"
)

SGML_BUNDLE = (
    b"<SEC-DOCUMENT>\n<SEC-HEADER>0001</SEC-HEADER>\n<TYPE>10-K\n"
    b"<FILENAME>acme-10k.htm\n<DOCUMENT>\n<TYPE>10-K\n"
    b"<SEQUENCE>1\n<FILENAME>acme-10k.htm\n<TEXT>\n"
    b"<HTML><BODY>PRIMARY DOCUMENT BODY</BODY></HTML>\n"
    b"</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>"
)


#: EDGAR SGML is line-oriented: the unpacker anchors its header tags at line starts.
_INVERTED_BUNDLE = (
    b"<SEC-DOCUMENT>\n"
    b"<DOCUMENT>\n<TYPE>EX-21\n<SEQUENCE>1\n<FILENAME>ex21.txt\n"
    b"<DESCRIPTION>CERTIFICATION OF INCORPORATION\n"
    b"<TEXT>\nEXHIBIT TWENTY ONE BODY\n</TEXT>\n</DOCUMENT>\n"
    b"<DOCUMENT>\n<TYPE>EX-99\n<SEQUENCE>2\n<FILENAME>ex99.htm\n"
    b"<DESCRIPTION>PRESS RELEASE\n"
    b"<TEXT>\nPRESS RELEASE BODY\n</TEXT>\n</DOCUMENT>\n"
    b"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>3\n<FILENAME>acme-10k.htm\n"
    b"<DESCRIPTION>ANNUAL REPORT\n"
    b"<TEXT>\n<HTML><BODY>PRIMARY DOCUMENT BODY</BODY></HTML>\n</TEXT>\n</DOCUMENT>\n"
    b"</SEC-DOCUMENT>\n"
)

#: A bundle whose selected primary is XML, though the locator requested the ``.txt``.
XML_CHILD_BUNDLE = (
    b"<SEC-DOCUMENT>\n"
    b"<DOCUMENT>\n<TYPE>4\n<SEQUENCE>1\n<FILENAME>ownership.xml\n"
    b'<TEXT>\n<?xml version="1.0"?><ownershipDocument><x>1</x></ownershipDocument>\n'
    b"</TEXT>\n</DOCUMENT>\n"
    b"</SEC-DOCUMENT>\n"
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
    extraction = extract_from_sgml_envelope(payload, _locator())
    assert extraction.payload == payload
    assert extraction.bundle is None
    assert extraction.submission.source_format is SubmissionFormat.DIRECT


def test_envelope_selects_the_target_sub_document() -> None:
    extraction = extract_from_sgml_envelope(SGML_BUNDLE, _locator())
    assert extraction.payload is not None
    assert b"PRIMARY DOCUMENT BODY" in extraction.payload
    assert b"<SEC-DOCUMENT>" not in extraction.payload
    assert extraction.bundle == SGML_BUNDLE


def test_empty_payload_extracts_to_nothing() -> None:
    extraction = extract_from_sgml_envelope(b"", _locator())
    assert extraction.payload is None
    assert extraction.bundle is None


def test_pem_envelope_is_unwrapped_before_scanning() -> None:
    pem = (
        b"-----BEGIN PRIVACY-ENHANCED MESSAGE-----\n"
        b"Proc-Type: ENCRYPTED\n\n"
        + SGML_BUNDLE
        + b"\n-----END PRIVACY-ENHANCED MESSAGE-----\n"
    )
    extraction = extract_from_sgml_envelope(pem, _locator())
    assert extraction.payload is not None
    assert b"PRIMARY DOCUMENT BODY" in extraction.payload
    assert extraction.bundle is not None


def test_single_document_bundle_resolves_to_that_document() -> None:
    """The unpacker falls back to the first available sub-document."""
    bundle = (
        b"<SEC-DOCUMENT><DOCUMENT><TYPE>EX-99.1</TYPE>\n<SEQUENCE>2</SEQUENCE>\n"
        b"<FILENAME>other.htm</FILENAME><TEXT><html>exhibit</html></TEXT>\n"
        b"</DOCUMENT></SEC-DOCUMENT>"
    )
    extraction = extract_from_sgml_envelope(bundle, _locator())
    assert extraction.payload == b"<html>exhibit</html>"
    assert extraction.bundle == bundle


def test_envelope_records_the_selected_header() -> None:
    extraction = extract_from_sgml_envelope(SGML_BUNDLE, _locator())
    assert extraction.submission is not None
    assert extraction.submission.selected_document.doc_type == "10-K"
    assert extraction.submission.selected_document.document_path == "acme-10k.htm"
    assert extraction.submission.selected_document.sequence == 1


def test_envelope_records_every_header_in_envelope_order() -> None:
    extraction = extract_from_sgml_envelope(_INVERTED_BUNDLE, _locator())
    assert extraction.submission is not None
    assert [doc.document_path for doc in extraction.submission.documents] == [
        "ex21.txt",
        "ex99.htm",
        "acme-10k.htm",
    ]
    assert extraction.submission.selected_index == 2


def test_envelope_records_carry_no_payload() -> None:
    """A sibling describes a document the fetcher never downloaded."""
    extraction = extract_from_sgml_envelope(_INVERTED_BUNDLE, _locator())
    assert extraction.submission is not None
    assert extraction.payload is not None
    assert b"EXHIBIT TWENTY ONE BODY" not in extraction.payload
    assert not hasattr(extraction.submission.documents[0], "payload")


def test_envelope_records_sequence_and_description_headers() -> None:
    extraction = extract_from_sgml_envelope(_INVERTED_BUNDLE, _locator())
    assert extraction.submission is not None
    by_name = {doc.document_path: doc for doc in extraction.submission.documents}
    assert by_name["ex21.txt"].sequence == 1
    assert by_name["ex21.txt"].doc_type == "EX-21"
    assert by_name["ex21.txt"].description == "CERTIFICATION OF INCORPORATION"


def test_envelope_header_missing_fields_are_recorded_as_absent() -> None:
    """A bare envelope must not invent a sequence or description."""
    bare = (
        b"<SEC-DOCUMENT><DOCUMENT><TYPE>10-K</TYPE>\n<FILENAME>a.htm</FILENAME>\n"
        b"<TEXT>body</TEXT></DOCUMENT></SEC-DOCUMENT>"
    )
    extraction = extract_from_sgml_envelope(bare, _locator())
    assert extraction.submission is not None
    assert extraction.submission.selected_document.sequence is None
    assert len(extraction.submission.documents) == 1


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
    assert result.acquired.selected_payload == b"<html>stored</html>"
    assert result.status == "ok"
    fetcher.close()


def test_fixture_fetcher_reports_missing(tmp_path: Path) -> None:
    fetcher = FixtureArchiveFetcher([tmp_path / "fix.sqlite"])
    result = fetcher.fetch(_locator())
    assert result.status == "missing"
    assert result.acquired is None
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
    assert b"PRIMARY DOCUMENT BODY" in result.acquired.selected_payload
    assert result.source_payload == SGML_BUNDLE
    fetcher.close()


def test_fixture_fetcher_checks_fixtures_in_order(tmp_path: Path) -> None:
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"
    locator = _locator()
    _seed_fixture(second, locator, b"<html>second</html>")
    fetcher = FixtureArchiveFetcher([first, second])
    assert fetcher.fetch(locator).acquired.selected_payload == b"<html>second</html>"
    fetcher.close()


def test_fixture_fetcher_is_picklable(tmp_path: Path) -> None:
    """The fetcher must survive the process-pool boundary it is shipped over."""
    db_path = tmp_path / "fix.sqlite"
    locator = _locator()
    _seed_fixture(db_path, locator, b"<html>pickled</html>")
    fetcher = FixtureArchiveFetcher([db_path])
    restored = pickle.loads(pickle.dumps(fetcher))
    assert restored.fetch(locator).acquired.selected_payload == b"<html>pickled</html>"
    fetcher.close()
    restored.close()


def test_fixture_fetcher_reports_failure_not_exception(tmp_path: Path) -> None:
    """A corrupt fixture becomes a failed status, never a raised exception."""
    db_path = tmp_path / "corrupt.sqlite"
    db_path.write_bytes(b"not a database")
    fetcher = FixtureArchiveFetcher([db_path])
    result = fetcher.fetch(_locator())
    assert result.status in {"failed", "missing"}
    assert result.acquired is None
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
    assert result.acquired.selected_payload == b"<html>broker</html>"
    assert len(broker.calls) == 1


def test_broker_fetcher_falls_back_to_the_submission_bundle() -> None:
    broker = FakeBroker({".txt": SGML_BUNDLE})
    result = BrokerArchiveFetcher(broker).fetch(_locator())
    assert result.ok is True
    assert b"PRIMARY DOCUMENT BODY" in result.acquired.selected_payload
    assert len(broker.calls) == 2


def test_broker_fetcher_skips_the_direct_url_for_a_stub() -> None:
    broker = FakeBroker({"0001.txt": SGML_BUNDLE, "0001.htm": b"<html>stub</html>"})
    result = BrokerArchiveFetcher(
        broker,
    ).fetch(_locator("acme-10k-0001.htm"))
    assert result.ok is True
    assert b"PRIMARY DOCUMENT BODY" in result.acquired.selected_payload


def test_broker_fetcher_probes_the_cache_first() -> None:
    broker = FakeBroker({"acme-10k.htm": b"<html>from broker</html>"})
    cache = FakeCacheReader({"acme-10k.htm": b"<html>from cache</html>"})
    result = BrokerArchiveFetcher(broker, cache_reader=cache).fetch(_locator())
    assert result.acquired.selected_payload == b"<html>from cache</html>"
    assert broker.calls == []


def test_broker_fetcher_only_misses_reach_the_socket() -> None:
    broker = FakeBroker({"acme-10k.htm": b"<html>from broker</html>"})
    cache = FakeCacheReader({"other.htm": b"<html>irrelevant</html>"})
    result = BrokerArchiveFetcher(broker, cache_reader=cache).fetch(_locator())
    assert result.acquired.selected_payload == b"<html>from broker</html>"
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
    assert result.acquired.selected_payload == b"<html>live</html>"
    assert client.calls == [ARCHIVE_URL]


def test_live_fetcher_falls_back_to_the_bundle() -> None:
    client = FakeHttpClient({".txt": SGML_BUNDLE})
    result = LiveArchiveFetcher(client).fetch(_locator())
    assert result.ok is True
    assert b"PRIMARY DOCUMENT BODY" in result.acquired.selected_payload
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
    assert result.acquired.selected_payload == b"<html>press release</html>"


def test_live_fetcher_exposes_metrics() -> None:
    client = FakeHttpClient({"acme-10k.htm": b"<html>x</html>"})
    assert LiveArchiveFetcher(client).metrics is client.metrics


# --- acquisition provenance ------------------------------------------------


def test_direct_fetch_records_the_url_it_served() -> None:
    client = FakeHttpClient({"acme-10k.htm": b"<html>live</html>"})

    result = LiveArchiveFetcher(client).fetch(_locator())

    assert result.acquired.source is not None
    assert result.acquired.source.kind is AcquisitionSourceKind.ARCHIVE_URL
    assert result.acquired.source.reference == ARCHIVE_URL


def test_bundle_fetch_records_the_bundle_url_not_the_requested_document_url() -> None:
    """The bundle is what answered, so its URL is the source."""
    client = FakeHttpClient({".txt": SGML_BUNDLE})

    result = LiveArchiveFetcher(client).fetch(_locator())

    assert result.acquired.source is not None
    assert result.acquired.source.reference.endswith(".txt")
    assert result.acquired.source.reference != ARCHIVE_URL


def test_rendered_locator_records_the_archive_root_url_it_actually_used() -> None:
    locator = _rendered_locator()
    client = FakeHttpClient({"/edgar.xml": b"<html>root original</html>"})

    result = LiveArchiveFetcher(client).fetch(locator)

    assert result.acquired.source is not None
    assert result.acquired.source.reference == RENDERED_ROOT_URL


def test_rendered_fallback_records_the_rendered_url() -> None:
    locator = _rendered_locator()
    client = FakeHttpClient({"xslF345X02/edgar.xml": b"<html>rendering</html>"})

    result = LiveArchiveFetcher(client).fetch(locator)

    assert result.acquired.source is not None
    assert result.acquired.source.reference == RENDERED_URL


def test_rendered_acquisition_keeps_the_requested_identity() -> None:
    locator = _rendered_locator()
    client = FakeHttpClient({"/edgar.xml": b"<html>root original</html>"})

    result = LiveArchiveFetcher(client).fetch(locator)

    assert result.locator.document_path == "xslF345X02/edgar.xml"
    assert result.locator.document_locator_key == derive_document_locator_key(
        ACCESSION, "xslF345X02/edgar.xml"
    )


def test_rendered_root_serving_an_xml_name_is_still_html_routed() -> None:
    """The root basename is named .xml, but the requested link was a rendering."""
    locator = _rendered_locator()
    client = FakeHttpClient({"/edgar.xml": b"<html>root original</html>"})

    acquired = LiveArchiveFetcher(client).fetch(locator).acquired

    assert acquired is not None
    assert acquired.selected_document.content_route is DocumentRoute.RENDERED
    assert acquired.requested_locator.document_path == "xslF345X02/edgar.xml"


def test_sgml_child_route_follows_the_child_not_the_requested_bundle() -> None:
    """An XML primary inside a .txt bundle is XML; the bundle's suffix is not its format."""
    bundle_locator = _bundle_locator()
    client = FakeHttpClient({".txt": XML_CHILD_BUNDLE})

    acquired = LiveArchiveFetcher(client).fetch(bundle_locator).acquired

    assert acquired is not None
    assert acquired.selected_document.content_route is DocumentRoute.XML


def test_sgml_child_route_leaves_the_requested_locator_untouched() -> None:
    bundle_locator = _bundle_locator()
    client = FakeHttpClient({".txt": XML_CHILD_BUNDLE})

    acquired = LiveArchiveFetcher(client).fetch(bundle_locator).acquired

    assert acquired is not None
    assert acquired.document_locator_key == bundle_locator.document_locator_key
    assert acquired.requested_locator.document_path == bundle_locator.document_path


def test_acquired_submission_reports_the_selected_payload_and_headers() -> None:
    client = FakeHttpClient({".txt": _INVERTED_BUNDLE})

    acquired = LiveArchiveFetcher(client).fetch(_locator()).acquired

    assert acquired is not None
    assert acquired.source_format is SubmissionFormat.SGML
    assert b"PRIMARY DOCUMENT BODY" in acquired.selected_payload
    assert acquired.selected_document.doc_type == "10-K"
    assert len(acquired.documents) == 3


def test_acquired_submission_carries_no_source_envelope() -> None:
    """The bundle is released after extraction; a 200MB submission must not be retained."""
    client = FakeHttpClient({".txt": _INVERTED_BUNDLE})

    result = LiveArchiveFetcher(client).fetch(_locator())

    assert result.acquired is not None
    assert not hasattr(result.acquired, "source_payload")
    assert result.source_payload == _INVERTED_BUNDLE


def test_direct_acquisition_describes_one_document() -> None:
    client = FakeHttpClient({"acme-10k.htm": b"<html>live</html>"})

    acquired = LiveArchiveFetcher(client).fetch(_locator()).acquired

    assert acquired is not None
    assert acquired.source_format is SubmissionFormat.DIRECT
    assert len(acquired.documents) == 1
    assert acquired.selected_document.content_route is DocumentRoute.MARKUP


def test_failed_fetch_has_no_acquired_submission() -> None:
    client = FakeHttpClient({})

    assert LiveArchiveFetcher(client).fetch(_locator()).acquired is None


def test_every_backend_records_a_source_for_a_successful_fetch(tmp_path: Path) -> None:
    """Provenance must not depend on which transport served the bytes."""
    db_path = tmp_path / "fix.sqlite"
    _seed_fixture(db_path, _locator(), b"<html>stored</html>")
    fixture_fetcher = FixtureArchiveFetcher([db_path])
    fixture_result = fixture_fetcher.fetch(_locator())
    fixture_fetcher.close()

    broker_result = BrokerArchiveFetcher(
        FakeBroker({"acme-10k.htm": b"<html>x</html>"})
    ).fetch(_locator())
    live_result = LiveArchiveFetcher(
        FakeHttpClient({"acme-10k.htm": b"<html>x</html>"})
    ).fetch(_locator())

    assert fixture_result.acquired.source is not None
    assert fixture_result.acquired.source.kind is AcquisitionSourceKind.FIXTURE
    assert fixture_result.acquired.source.reference == "acme-10k.htm"
    assert broker_result.acquired.source is not None
    assert broker_result.acquired.source.kind is AcquisitionSourceKind.ARCHIVE_URL
    assert live_result.acquired.source is not None
    assert live_result.acquired.source.kind is AcquisitionSourceKind.ARCHIVE_URL


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


# --- Rendered path resolution ---------------------------------------------

RENDERED_URL = (
    "https://www.sec.gov/Archives/edgar/data/1234567/000123456711000001/"
    "xslF345X02/edgar.xml"
)
RENDERED_ROOT_URL = (
    "https://www.sec.gov/Archives/edgar/data/1234567/000123456711000001/edgar.xml"
)


def _rendered_locator() -> DocumentLocator:
    return DocumentLocator.from_parts(
        ACCESSION,
        "xslF345X02/edgar.xml",
        archive_url=RENDERED_URL,
        form="4",
    )


def _bundle_locator() -> DocumentLocator:
    return DocumentLocator.from_parts(
        ACCESSION,
        f"{accession_hyphenated(ACCESSION)}.txt",
        archive_url=f"{RENDERED_ROOT_URL.rsplit('/', 1)[0]}/"
        f"{accession_hyphenated(ACCESSION)}.txt",
        form="4",
    )


def test_archive_root_url_derives_the_original() -> None:
    assert archive_root_url(_rendered_locator()) == RENDERED_ROOT_URL


def test_archive_root_url_is_none_for_a_flat_path() -> None:
    assert archive_root_url(_locator()) is None


@pytest.mark.parametrize(
    "url",
    [
        RENDERED_URL.replace("000123456711000001", "000123456711000002"),
    ],
)
def test_archive_candidates_require_locator_accession_scope(url: str) -> None:
    locator = DocumentLocator.from_parts(
        ACCESSION,
        "xslF345X02/edgar.xml",
        archive_url=url,
        form="4",
    )

    assert _submission_targets(locator) == (None, None)
    assert archive_root_url(locator) is None

    client = FakeHttpClient({})
    fetcher = LiveArchiveFetcher(client)
    fetcher.fetch(locator)
    assert fetcher.fetch_bundle(locator).status == "missing"
    assert client.calls == []


def test_archive_candidate_keeps_archive_cik_distinct_from_source_cik() -> None:
    accession = "0000950134-01-500666"
    url = "https://www.sec.gov/Archives/edgar/data/4515/000095013401500666/primary.htm"
    locator = DocumentLocator.from_parts(
        accession,
        "primary.htm",
        archive_url=url,
        source_cik="950134",
        form="10-Q",
    )

    direct_url, bundle_url = _submission_targets(locator)

    assert direct_url == url
    assert bundle_url == (
        "https://www.sec.gov/Archives/edgar/data/4515/"
        "000095013401500666/0000950134-01-500666.txt"
    )


def test_resolution_does_not_alter_locator_identity() -> None:
    """Only the fetched URL may change; the key names the catalog's path."""
    locator = _rendered_locator()

    archive_root_url(locator)

    assert locator.document_path == "xslF345X02/edgar.xml"
    assert locator.document_locator_key == derive_document_locator_key(
        ACCESSION, "xslF345X02/edgar.xml"
    )


def test_live_fetcher_prefers_the_archive_root_over_the_rendering() -> None:
    client = FakeHttpClient(
        {"/xslF345X02/edgar.xml": b"RENDERED", "/edgar.xml": b"ORIGINAL"}
    )

    result = LiveArchiveFetcher(client).fetch(_rendered_locator())

    assert result.ok
    assert result.acquired.selected_payload == b"ORIGINAL"
    assert client.calls == [RENDERED_ROOT_URL]


def test_live_fetcher_falls_back_to_the_rendering() -> None:
    """A root document that does not exist must not lose a reachable filing."""
    client = FakeHttpClient({"/xslF345X02/edgar.xml": b"RENDERED"})

    result = LiveArchiveFetcher(client).fetch(_rendered_locator())

    assert result.ok
    assert result.acquired.selected_payload == b"RENDERED"
    assert client.calls == [RENDERED_ROOT_URL, RENDERED_URL]


def test_broker_fetcher_prefers_the_archive_root() -> None:
    broker = FakeBroker(
        {"/xslF345X02/edgar.xml": b"RENDERED", "/edgar.xml": b"ORIGINAL"}
    )

    result = BrokerArchiveFetcher(broker).fetch(_rendered_locator())

    assert result.ok
    assert result.acquired.selected_payload == b"ORIGINAL"


def test_flat_path_fetches_directly(tmp_path: Path) -> None:
    client = FakeHttpClient({"/acme-10k.htm": SGML_BUNDLE})

    result = LiveArchiveFetcher(client).fetch(_locator())

    assert result.ok
    assert client.calls == [ARCHIVE_URL]


def test_fixture_fetcher_resolves_the_archive_root_first(tmp_path: Path) -> None:
    locator = _rendered_locator()
    db_path = tmp_path / "fixture.sqlite"
    _seed_fixture(db_path, locator, b"RENDERED")
    _seed_fixture(
        db_path,
        DocumentLocator.from_parts(
            ACCESSION, "edgar.xml", archive_url=RENDERED_ROOT_URL, form="4"
        ),
        b"ORIGINAL",
    )
    fetcher = FixtureArchiveFetcher([db_path])

    result = fetcher.fetch(locator)

    assert result.ok
    assert result.acquired.selected_payload == b"ORIGINAL"
    fetcher.close()


# --- the candidate gate is advisory ----------------------------------------

ERA_ACCESSION = "0000890923-01-000002"
ERA_BUNDLE_SUFFIX = "/0000890923-01-000002.txt"


def _era_locator(
    document_path: str = "ex21.txt", form: str = "10-K"
) -> DocumentLocator:
    """A 2001 exhibit-named locator: exactly the request the candidate gate flags."""
    return DocumentLocator.from_parts(
        ERA_ACCESSION,
        document_path,
        archive_url=(
            f"https://www.sec.gov/Archives/edgar/data/890923/"
            f"000089092301000002/{document_path}"
        ),
        form=form,
    )


def test_a_candidate_is_not_promoted_to_the_bundle_by_the_broker() -> None:
    """The bundle is one click away and must stay unrequested; recovery is deferred."""
    broker = FakeBroker(
        {
            "/ex21.txt": b"EXHIBIT TWENTY ONE BODY",
            ERA_BUNDLE_SUFFIX: _INVERTED_BUNDLE,
        }
    )

    result = BrokerArchiveFetcher(broker).fetch(_era_locator())

    assert broker.calls == [_era_locator().archive_url]
    assert result.ok
    assert result.acquired.selected_payload == b"EXHIBIT TWENTY ONE BODY"
    assert result.acquired.selected_index == 0
    assert len(result.acquired.documents) == 1


def test_a_candidate_is_not_promoted_to_the_bundle_by_the_live_client() -> None:
    client = FakeHttpClient(
        {
            "/ex21.txt": b"EXHIBIT TWENTY ONE BODY",
            ERA_BUNDLE_SUFFIX: _INVERTED_BUNDLE,
        }
    )

    result = LiveArchiveFetcher(client).fetch(_era_locator())

    assert client.calls == [_era_locator().archive_url]
    assert result.ok
    assert result.acquired.selected_payload == b"EXHIBIT TWENTY ONE BODY"
    assert result.acquired.source_format is SubmissionFormat.DIRECT


def test_a_candidate_decision_leaves_the_worker_row_unchanged(tmp_path: Path) -> None:
    """Snapshot identity is the requested locator's, whatever the gate concluded."""
    broker = FakeBroker(
        {
            "/ex21.txt": b"EXHIBIT TWENTY ONE BODY",
            ERA_BUNDLE_SUFFIX: _INVERTED_BUNDLE,
        }
    )
    locator = _era_locator()

    result = process_chunk(
        "c1",
        "w1",
        [locator],
        [
            FilingOccurrence(
                occurrence_id="occ-1",
                source_cik=Cik.from_raw("890923"),
                accession=locator.accession,
                document_path=locator.document_path,
                form="10-K",
                filing_date="2001-03-01",
                report_date=None,
                doc_id=locator.document_locator_key,
            )
        ],
        fetcher=BrokerArchiveFetcher(broker),
        processor=PassThroughProcessor(),
        chunks_dir=tmp_path,
    )

    assert result.bundle_candidate_count == 1
    assert result.normalized_count == 2
    table = pq.read_table(result.output_path)
    rows = {
        path: (payload, metadata)
        for path, payload, metadata in zip(
            table.column("document_path").to_pylist(),
            table.column("raw_payload").to_pylist(),
            table.column("metadata").to_pylist(),
            strict=True,
        )
    }
    assert rows[locator.document_path][0] == b"EXHIBIT TWENTY ONE BODY"
    assert b"PRIMARY DOCUMENT BODY" in rows["acme-10k.htm"][0]
    assert json.loads(rows[locator.document_path][1])["document_role"] == "exhibit"
    assert json.loads(rows["acme-10k.htm"][1])["document_role"] == "primary"
