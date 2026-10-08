"""Tests for fixture discovery and fill/resume behavior."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from edgar_sec.domain.document.models import DocumentLocator
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.runtime.fixtures import validate_fixture_component
from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.pipelines.document_storage.fetching import FixtureArchiveFetcher
from edgar_sec.pipelines.document_storage.fixture_operator import (
    FixtureOperatorError,
    fill_fixture,
    list_fixtures,
)
from edgar_sec.pipelines.document_storage.fixture_store import FixtureStore
from edgar_sec.pipelines.document_storage.paths import DocumentStoragePaths


def _locator(name: str) -> DocumentLocator:
    return DocumentLocator.from_parts(
        "0001234567-11-000001",
        name,
        archive_url=f"https://www.sec.gov/Archives/{name}",
        form="10-K",
    )


def _paths(root: Path) -> DocumentStoragePaths:
    return DocumentStoragePaths(root / ".artifacts")


class FakeClient:
    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        for suffix, response in self.responses.items():
            if url.endswith(suffix):
                if isinstance(response, Exception):
                    raise response
                return response
        raise OSError("no response")


def test_fill_skips_existing_rows_and_retries_failures(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    existing = _locator("existing.htm")
    missing = _locator("missing.htm")
    successful = _locator("new.htm")
    with FixtureStore(paths.fixture_db_path("fix-fill")) as store:
        store.put_many([(existing.document_locator_key, b"original")])

    client = FakeClient(
        {
            "missing.htm": OSError("temporary outage"),
            "new.htm": b"new payload",
        }
    )
    first = fill_fixture(
        paths=paths,
        fixture_id="fix-fill",
        locators=[existing, missing, successful],
        workers=2,
        http_client=client,
        target_reference="/tmp/plan.json",
    )
    assert first.requested == 3
    assert first.already_present == 1
    assert first.newly_written == 1
    assert first.failed == 1
    assert len(client.calls) == 2

    retry_client = FakeClient({"missing.htm": b"recovered"})
    second = fill_fixture(
        paths=paths,
        fixture_id="fix-fill",
        locators=[existing, missing, successful],
        workers=1,
        http_client=retry_client,
    )
    assert second.already_present == 2
    assert second.newly_written == 1
    assert second.failed == 0

    fetcher = FixtureArchiveFetcher([paths.fixture_db_path("fix-fill")])
    assert fetcher.fetch(missing).acquired.selected_payload == b"recovered"
    assert fetcher.fetch(successful).acquired.selected_payload == b"new payload"
    fetcher.close()

    manifest = json.loads(paths.fixture_manifest_path("fix-fill").read_text())
    assert manifest["manifest_version"] == 1
    assert manifest["fixture_kind"] == "document_storage.raw_payload"
    assert manifest["storage"] == {"format": "sqlite", "path": "fixture.sqlite"}
    assert manifest["details"]["payload_count"] == 3
    assert manifest["details"]["last_fill"]["failed"] == 0
    assert manifest["details"]["last_fill"]["target_reference"] is None


def test_fill_persists_the_complete_submission_bundle(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    locator = DocumentLocator.from_parts(
        "0001234567-11-000001",
        "primary.htm",
        archive_url=(
            "https://www.sec.gov/Archives/edgar/data/1234567/"
            "000123456711000001/primary.htm"
        ),
        form="10-K",
    )
    bundle = (
        b"<SEC-DOCUMENT><DOCUMENT><TYPE>10-K</TYPE><SEQUENCE>1</SEQUENCE>"
        b"<FILENAME>primary.htm</FILENAME><TEXT><html>body</html></TEXT>"
        b"</DOCUMENT></SEC-DOCUMENT>"
    )
    client = FakeClient({"primary.htm": OSError("404"), ".txt": bundle})
    fill_fixture(
        paths=paths,
        fixture_id="fix-bundle",
        locators=[locator],
        workers=1,
        http_client=client,
    )
    fetcher = FixtureArchiveFetcher([paths.fixture_db_path("fix-bundle")])
    result = fetcher.fetch(locator)
    assert result.ok
    assert result.acquired.selected_payload == b"<html>body</html>"
    assert result.source_payload == bundle
    fetcher.close()


def test_fill_records_document_metadata_for_every_locator(tmp_path: Path) -> None:
    """A payload key is one-way, so accession, path, and MIME are written down."""
    paths = _paths(tmp_path)
    html = _locator("page.htm")
    text = DocumentLocator.from_parts(
        "0001234567-11-000002",
        "notes.txt",
        archive_url="https://www.sec.gov/Archives/notes.txt",
        form="10-Q",
    )
    fill_fixture(
        paths=paths,
        fixture_id="fix-meta",
        locators=[html, text],
        workers=2,
        http_client=FakeClient(
            {"page.htm": b"<html>body</html>", "notes.txt": b"plain text"}
        ),
    )
    with FixtureStore(paths.fixture_db_path("fix-meta"), read_only=True) as store:
        assert store.has_document_metadata
        recorded = {item.doc_id: item for item in store.documents()}
        assert set(recorded) == {html.document_locator_key, text.document_locator_key}
        page = recorded[html.document_locator_key]
        assert page.accession == "0001234567-11-000001"
        assert page.document_path == "page.htm"
        assert page.mime_type == "text/html"
        assert page.byte_size == len(b"<html>body</html>")
        assert recorded[text.document_locator_key].mime_type == "text/plain"
        # The form selects the processing plugin, so losing it changes review.
        assert store.document_forms() == {
            html.document_locator_key: "10-K",
            text.document_locator_key: "10-Q",
        }


def test_refill_backfills_metadata_without_refetching(tmp_path: Path) -> None:
    """Re-running the same fill must not touch the network."""
    paths = _paths(tmp_path)
    locator = _locator("retained.htm")
    with FixtureStore(paths.fixture_db_path("fix-retained")) as store:
        store.put_many([(locator.document_locator_key, b"retained payload")])
    with sqlite3.connect(paths.fixture_db_path("fix-retained")) as connection:
        connection.execute("DROP TABLE document_blobs")
        connection.commit()

    client = FakeClient({"retained.htm": b"must not be fetched"})
    report = fill_fixture(
        paths=paths,
        fixture_id="fix-retained",
        locators=[locator],
        workers=1,
        http_client=client,
    )
    assert report.already_present == 1
    assert report.newly_written == 0
    assert report.backfilled_metadata == 1
    assert client.calls == []
    with FixtureStore(paths.fixture_db_path("fix-retained"), read_only=True) as store:
        assert store.documents()[0].raw_payload_sha256 == sha256_bytes(
            b"retained payload"
        )
        assert store.get(locator.document_locator_key) == b"retained payload"


def test_fixture_discovery_reports_manifest_and_payload_count(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    locator = _locator("stored.htm")
    fill_fixture(
        paths=paths,
        fixture_id="fix-list",
        locators=[locator],
        workers=1,
        http_client=FakeClient({"stored.htm": b"stored"}),
    )
    fixtures = list_fixtures(paths)
    assert len(fixtures) == 1
    assert fixtures[0].fixture_id == "fix-list"
    assert fixtures[0].payload_count == 1
    assert fixtures[0].manifest_status == "valid"


def test_fixture_ids_cannot_escape_fixture_root() -> None:
    for fixture_id in ("../outside", ".", "", "/tmp/outside"):
        try:
            validate_fixture_component(fixture_id, "fixture_id")
        except ValueError:
            continue
        raise AssertionError(f"accepted unsafe fixture id {fixture_id!r}")
