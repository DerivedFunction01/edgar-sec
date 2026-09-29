"""Immutable external source snapshot tests.

Split from ``test_augmentation.py`` so each source module owns one mirrored test
file (AGENTS.md §6.3). The lifecycle under test is capture → content-address →
publish → verify, and the property that matters is that an unchanged fetch is a
no-op while a changed payload produces a new snapshot rather than an overwrite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_MANIFEST_KIND,
    SOURCE_NAME,
    SOURCE_SCHEMA_VERSION,
    SOURCE_URL,
    SourceRegistryError,
    load_source_snapshot,
    parse_company_tickers,
    refresh_company_tickers,
    source_snapshot_id,
)
from tests.support import FakeSession, build_test_http

TICKERS = {
    "0": {"cik_str": "37996", "ticker": "F", "title": "FORD MOTOR CO"},
    "1": {"cik_str": "20", "ticker": "KTC", "title": "K Tron International Inc"},
}


def _payload(entries: dict) -> bytes:
    return json.dumps(entries).encode("utf-8")


def test_snapshot_id_is_content_addressed() -> None:
    digest = sha256_bytes(b"payload")
    assert source_snapshot_id(digest) == source_snapshot_id(digest)
    assert source_snapshot_id(digest) != source_snapshot_id("other")
    assert len(source_snapshot_id(digest)) == 32


def test_parse_normalizes_and_orders_listings() -> None:
    listings, report = parse_company_tickers(
        _payload(TICKERS), snapshot_id="snap", observed_at="2026-01-01T00:00:00Z"
    )
    assert [row["cik_padded"] for row in listings] == ["0000000020", "0000037996"]
    assert listings[0]["ticker"] == "KTC"
    assert listings[0]["source_snapshot_id"] == "snap"
    assert report["listing_row_count"] == 2
    assert report["unique_cik_count"] == 2
    assert report["malformed_row_count"] == 0


def test_parse_counts_duplicate_listings() -> None:
    payload = {
        **TICKERS,
        "2": {"cik_str": "20", "ticker": "KTC", "title": "K Tron International Inc"},
    }
    _listings, report = parse_company_tickers(
        _payload(payload), snapshot_id="snap", observed_at="2026-01-01T00:00:00Z"
    )
    assert report["listing_row_count"] == 3
    assert report["unique_cik_count"] == 2
    assert report["duplicate_listing_count"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        json.dumps({"0": {"ticker": "A", "title": "B"}}).encode(),
        json.dumps({"0": {"cik_str": "abc", "ticker": "A", "title": "B"}}).encode(),
        json.dumps({"0": {"cik_str": 20, "ticker": 1, "title": 2}}).encode(),
    ],
)
def test_a_single_malformed_entry_rejects_the_snapshot(payload: bytes) -> None:
    """A partial listing would silently shrink the CIK universe."""
    with pytest.raises(SourceRegistryError):
        parse_company_tickers(
            payload, snapshot_id="snap", observed_at="2026-01-01T00:00:00Z"
        )


def test_refresh_publishes_immutable_snapshot(
    session: FakeSession, tmp_path: Path
) -> None:
    session.register_bytes(SOURCE_URL, _payload(TICKERS))
    metadata = resolve_metadata_paths(tmp_path)

    manifest = refresh_company_tickers(
        metadata_paths=metadata, client=build_test_http(session)
    )
    assert manifest["validation_status"] == "ok"
    assert manifest["manifest_kind"] == SOURCE_MANIFEST_KIND
    assert manifest["source"] == SOURCE_NAME
    assert manifest["manifest_schema_version"] == SOURCE_SCHEMA_VERSION
    assert manifest["unique_cik_count"] == 2
    assert manifest["raw_path"] == str(
        metadata.source_snapshot_file(SOURCE_NAME, manifest["snapshot_id"])
    )
    assert metadata.source_manifest_file(SOURCE_NAME, manifest["snapshot_id"]).is_file()

    loaded = load_source_snapshot(
        metadata.source_manifest_file(SOURCE_NAME, manifest["snapshot_id"])
    )
    assert loaded.manifest["raw_sha256"] == manifest["raw_sha256"]
    assert loaded.raw_path.read_bytes() == _payload(TICKERS)


def test_refetching_unchanged_content_is_a_no_op(
    session: FakeSession, tmp_path: Path
) -> None:
    session.register_bytes(SOURCE_URL, _payload(TICKERS))
    metadata = resolve_metadata_paths(tmp_path)
    client = build_test_http(session)

    first = refresh_company_tickers(metadata_paths=metadata, client=client)
    again = refresh_company_tickers(metadata_paths=metadata, client=client)
    assert again["snapshot_id"] == first["snapshot_id"]

    snapshots = list((metadata.metadata_root / "sources" / SOURCE_NAME).iterdir())
    assert len(snapshots) == 1


def test_changed_payload_creates_a_second_snapshot(
    session: FakeSession, tmp_path: Path
) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    client = build_test_http(session)

    session.register_bytes(SOURCE_URL, _payload(TICKERS))
    first = refresh_company_tickers(metadata_paths=metadata, client=client)
    session.register_bytes(
        SOURCE_URL,
        _payload({**TICKERS, "2": {"cik_str": "5555", "ticker": "Z", "title": "Z"}}),
    )
    second = refresh_company_tickers(metadata_paths=metadata, client=client)

    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["listing_row_count"] == 3
    original = metadata.source_snapshot_file(SOURCE_NAME, first["snapshot_id"])
    assert original.read_bytes() == _payload(TICKERS)


def test_tampered_snapshot_is_rejected_on_load(
    session: FakeSession, tmp_path: Path
) -> None:
    session.register_bytes(SOURCE_URL, _payload(TICKERS))
    metadata = resolve_metadata_paths(tmp_path)
    manifest = refresh_company_tickers(
        metadata_paths=metadata, client=build_test_http(session)
    )
    raw = Path(manifest["raw_path"])
    raw.write_text("{}", encoding="utf-8")

    with pytest.raises(SourceRegistryError, match="hash does not match"):
        load_source_snapshot(
            metadata.source_manifest_file(SOURCE_NAME, manifest["snapshot_id"])
        )


def test_load_rejects_a_foreign_manifest(tmp_path: Path) -> None:
    from edgar_sec.infra.storage.atomic import atomic_write_json

    path = tmp_path / "manifest.json"
    atomic_write_json(path, {"manifest_kind": "something_else"}, canonical=False)
    with pytest.raises(SourceRegistryError, match="not a company ticker"):
        load_source_snapshot(path)


def test_load_reports_a_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_source_snapshot(tmp_path / "absent.json")
