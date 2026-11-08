"""Feed ingest: fetch, store, and skip behaviour over a fake SEC client."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from edgar_sec.domain.sec_urls import feed_archive_url
from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
from edgar_sec.pipelines.document_acquisition.feed_ingest import (
    SOURCE_ID,
    ingest_feed_archives,
)
from edgar_sec.pipelines.document_acquisition.options import feed_ingest_options
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from tests.pipelines.document_acquisition.feed_fixtures import (
    feed_tarball,
    listing_html,
    sgml_bundle,
)

_Q1_LISTING = listing_html("20240215.nc.tar.gz", "20240331.nc.tar.gz")
_Q2_LISTING = listing_html("20240401.nc.tar.gz", "20240520.nc.tar.gz")

_TARBALLS = {
    "20240331.nc.tar.gz": feed_tarball(
        {
            "20240331/000032019324000001/0000320193-24-000001.txt": sgml_bundle(
                accession="0000320193-24-000001", filed=date(2024, 3, 31)
            )
        }
    ),
    "20240401.nc.tar.gz": feed_tarball(
        {
            "20240401/000032019324000002/0000320193-24-000002.txt": sgml_bundle(
                accession="0000320193-24-000002", filed=date(2024, 4, 1)
            )
        }
    ),
}


class _FakeHttp:
    """Listings and tarballs for 2024 Q1/Q2; records streamed URLs."""

    def __init__(self) -> None:
        self.streamed_urls: list[str] = []

    def get_text(self, url: str) -> str:
        if url.endswith("/2024/QTR1/"):
            return _Q1_LISTING
        if url.endswith("/2024/QTR2/"):
            return _Q2_LISTING
        raise AssertionError(f"unexpected listing url: {url}")

    def stream_to_file(self, url: str, destination: Path, **kwargs: object) -> object:
        self.streamed_urls.append(url)
        filename = url.rsplit("/", 1)[-1]
        Path(destination).write_bytes(_TARBALLS[filename])
        return object()

    def close(self) -> None:
        pass


def _fake_http() -> _FakeHttp:
    return _FakeHttp()


def _options(tmp_path: Path):
    return feed_ingest_options(
        start=date(2024, 3, 31), end=date(2024, 4, 1), artifacts_root=tmp_path
    )


def test_ingest_fetches_in_range_units_and_publishes(tmp_path: Path) -> None:
    http = _fake_http()
    result = ingest_feed_archives(_options(tmp_path), http=http)  # type: ignore[arg-type]
    assert result.units_considered == 2
    assert result.units_fetched == 2
    assert result.units_from_store == 0
    assert result.units_skipped == 0
    assert result.bundles == 2
    assert result.malformed_bundles == 0
    assert result.new_rows == 2
    assert result.total_rows == 2
    assert result.published is True
    assert len(http.streamed_urls) == 2


def test_reingest_skips_stored_and_published_units(tmp_path: Path) -> None:
    options = _options(tmp_path)
    ingest_feed_archives(options, http=_fake_http())  # type: ignore[arg-type]
    http = _fake_http()
    result = ingest_feed_archives(options, http=http)  # type: ignore[arg-type]
    assert result.units_skipped == 2
    assert result.units_fetched == 0
    assert result.units_from_store == 0
    assert result.new_rows == 0
    assert result.published is False
    assert http.streamed_urls == []


def test_stored_but_unpublished_units_come_from_store(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    store = BulkArchiveStore(paths.bulk_archives_root)
    for filename, quarter in (("20240331.nc.tar.gz", 1), ("20240401.nc.tar.gz", 2)):
        staging = tmp_path / filename
        staging.write_bytes(_TARBALLS[filename])
        store.put_file(
            SOURCE_ID,
            staging,
            source_url=feed_archive_url(2024, quarter, filename),
        )
    http = _fake_http()
    result = ingest_feed_archives(_options(tmp_path), http=http)  # type: ignore[arg-type]
    assert result.units_from_store == 2
    assert result.units_fetched == 0
    assert result.new_rows == 2
    assert result.published is True
    assert http.streamed_urls == []
