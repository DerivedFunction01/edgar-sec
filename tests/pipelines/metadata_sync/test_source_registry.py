"""Metadata source refresh delegates to shared official source cohorts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.infra.storage.cohort.sources import resolve_active_source
from edgar_sec.pipelines.metadata_sync.cohort_adapter import cohort_record_to_roster
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.registry import RegistryError, compare_sources
from edgar_sec.pipelines.metadata_sync.source_registry import (
    SOURCE_NAME,
    SOURCE_URL,
    SourceRegistryError,
    parse_company_tickers,
    refresh_company_tickers,
)
from tests.support import FakeSession, build_test_http, fixture_path

TICKERS = {
    "0": {"cik_str": "37996", "ticker": "F", "title": "FORD MOTOR CO"},
    "1": {"cik_str": "20", "ticker": "KTC", "title": "K Tron International Inc"},
}


def _payload(entries: dict) -> bytes:
    return json.dumps(entries).encode("utf-8")


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
    assert manifest["source"] == SOURCE_NAME
    assert manifest["unique_cik_count"] == 2
    paths = resolve_cohort_paths(metadata.artifacts_root)
    record = CohortCatalog(paths).resolve_cohort_identifier(manifest["cohort_id"])
    assert record.tags == ("official-source", f"source:{SOURCE_NAME}", "system")
    assert cohort_record_to_roster(record, paths).row_count == 2
    assert Path(manifest["raw_path"]).read_bytes() == _payload(TICKERS)


def test_refetching_unchanged_content_is_a_no_op(
    session: FakeSession, tmp_path: Path
) -> None:
    session.register_bytes(SOURCE_URL, _payload(TICKERS))
    metadata = resolve_metadata_paths(tmp_path)
    client = build_test_http(session)

    first = refresh_company_tickers(metadata_paths=metadata, client=client)
    again = refresh_company_tickers(metadata_paths=metadata, client=client)
    assert again["snapshot_id"] == first["snapshot_id"]

    paths = resolve_cohort_paths(metadata.artifacts_root)
    records = CohortCatalog(paths).list_cohorts(tag=f"source:{SOURCE_NAME}")
    assert len(records) == 1
    assert (
        resolve_active_source(SOURCE_NAME, catalog=CohortCatalog(paths)).cohort_id
        == records[0].cohort_id
    )


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
    original = Path(first["raw_path"])
    assert original.read_bytes() == _payload(TICKERS)


def test_tampered_source_payload_is_rejected_for_registry_projection(
    session: FakeSession, tmp_path: Path
) -> None:
    session.register_bytes(SOURCE_URL, _payload(TICKERS))
    metadata = resolve_metadata_paths(tmp_path)
    manifest = refresh_company_tickers(
        metadata_paths=metadata, client=build_test_http(session)
    )
    raw = Path(manifest["raw_path"])
    raw.write_text("{}", encoding="utf-8")

    with pytest.raises(RegistryError, match="payload digest"):
        compare_sources(
            curated_input_path=fixture_path("cik_sec_mini.csv"),
            source_cohort_id=manifest["cohort_id"],
            metadata_paths=metadata,
        )
