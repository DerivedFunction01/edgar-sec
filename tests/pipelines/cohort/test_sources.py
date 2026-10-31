import json
from pathlib import Path

import pytest
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.cohort import sources
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.pipelines.cohort.sources import (
    SOURCE_URLS,
    publish_tickers_source,
    publish_universe_source,
    refresh_official_source,
    resolve_active_source,
    swap_active_source_pointer,
)
from tests.support import FakeSession, build_test_http, fixture_path


def test_universe_source_publishes_pinned_system_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    source_path = fixture_path("cik_lookup_universe_mini.txt")
    record = publish_universe_source(source_path, paths=paths, catalog=catalog)

    def no_reparse():
        raise AssertionError("intact source snapshot should be reused without parsing")

    monkeypatch.setattr(sources, "connect", no_reparse)
    repeated = publish_universe_source(source_path, paths=paths, catalog=catalog)

    assert record.origin_kind == "official_source"
    assert record.pinned
    assert {"system", "official-source", "source:cik_lookup"} <= set(record.tags)
    details = json.loads(record.origin_json)
    assert details["source_name"] == "cik_lookup"
    assert len(details["raw_sha256"]) == 64
    assert record.cohort_id == f"c-{details['source_snapshot_id'][:16]}"
    assert details["line_count"] == 14
    assert details["distinct_cik_count"] == record.row_count
    assert "raw_path" not in details
    assert repeated == record
    assert not (paths.cohorts_root / "source_snapshots").exists()
    assert resolve_active_source("cik_lookup", catalog=catalog) is None


def test_ticker_snapshots_with_changed_names_keep_separate_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = CohortPaths(tmp_path / "artifacts")
    catalog = CohortCatalog(paths)
    first_source = tmp_path / "tickers_first.json"
    changed_source = tmp_path / "tickers_changed.json"
    first_source.write_text(
        json.dumps(
            {
                "0": {"cik_str": 20, "ticker": "B", "title": "Beta Inc"},
                "1": {"cik_str": 10, "ticker": "A", "title": "Alpha Inc"},
            }
        ),
        encoding="utf-8",
    )
    changed_source.write_text(
        json.dumps(
            {
                "0": {"cik_str": 20, "ticker": "B", "title": "Beta Holdings"},
                "1": {"cik_str": 10, "ticker": "A", "title": "Alpha Group"},
            }
        ),
        encoding="utf-8",
    )

    first = publish_tickers_source(first_source, paths=paths, catalog=catalog)
    changed = publish_tickers_source(changed_source, paths=paths, catalog=catalog)

    def no_reparse(*_args, **_kwargs):
        raise AssertionError("intact source snapshot should be reused without parsing")

    monkeypatch.setattr(sources, "connect", no_reparse)
    repeated = publish_tickers_source(first_source, paths=paths, catalog=catalog)

    first_details = json.loads(first.origin_json)
    changed_details = json.loads(changed.origin_json)
    assert first.cohort_id == f"c-{first_details['source_snapshot_id'][:16]}"
    assert changed.cohort_id == f"c-{changed_details['source_snapshot_id'][:16]}"
    assert first.cohort_id != changed.cohort_id
    assert first.roster_id == changed.roster_id
    assert first.dataset_sha256 != changed.dataset_sha256
    assert repeated == first
    assert catalog.get_cohort(first.cohort_id) == first
    assert catalog.get_cohort(changed.cohort_id) == changed
    assert not (paths.cohorts_root / "source_snapshots").exists()

    swap_active_source_pointer("company_tickers", changed.cohort_id, catalog=catalog)
    assert catalog.get_active_source_pointer("company_tickers") == changed.cohort_id


def test_lookup_duplicate_names_use_first_nonempty_source_row(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "lookup.txt"
    raw.write_text(
        ":20:\nZed Corporation:20:\nAlpha Corporation:20:\n", encoding="utf-8"
    )
    paths = CohortPaths(tmp_path / "artifacts")
    record = publish_universe_source(raw, paths=paths, catalog=CohortCatalog(paths))

    rows = pq.read_table(paths.resolve_relative_path(record.dataset_path)).to_pylist()
    assert rows == [
        {"ordinal": 0, "cik_padded": "0000000020", "name": "Zed Corporation"}
    ]


def test_refresh_tickers_sets_pointer_only_after_valid_publication(
    tmp_path: Path,
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    session = FakeSession()
    session.register(
        SOURCE_URLS["company_tickers"],
        {
            "0": {"cik_str": 20, "ticker": "B", "title": "Beta Inc"},
            "1": {"cik_str": 10, "ticker": "A", "title": "Alpha Inc"},
            "2": {"cik_str": 20, "ticker": "BB", "title": "Beta Inc"},
        },
    )
    client = build_test_http(session)

    first = refresh_official_source(
        "company_tickers", client=client, paths=paths, catalog=catalog
    )
    assert resolve_active_source("company_tickers", catalog=catalog) == first
    assert first.pinned
    assert first.row_count == 2
    details = json.loads(first.origin_json)
    assert details["raw_sha256"]
    assert "raw_path" not in details
    assert not (paths.cohorts_root / "source_snapshots").exists()

    session.register_bytes(SOURCE_URLS["company_tickers"], b'{"bad":')
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        refresh_official_source(
            "company_tickers", client=client, paths=paths, catalog=catalog
        )

    assert resolve_active_source("company_tickers", catalog=catalog) == first


def test_refresh_reuses_intact_payload_before_parsing_and_reactivates_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    payload = b'{"0":{"cik_str":10,"ticker":"A","title":"Alpha Inc"}}'
    session = FakeSession()
    session.register_bytes(SOURCE_URLS["company_tickers"], payload)
    client = build_test_http(session)
    first = refresh_official_source(
        "company_tickers", client=client, paths=paths, catalog=catalog
    )
    other_payload = tmp_path / "other-tickers.json"
    other_payload.write_text(
        '{"0":{"cik_str":11,"ticker":"B","title":"Beta Inc"}}',
        encoding="utf-8",
    )
    other = publish_tickers_source(other_payload, paths=paths, catalog=catalog)
    swap_active_source_pointer("company_tickers", other.cohort_id, catalog=catalog)

    def no_reparse(*_args, **_kwargs):
        raise AssertionError("intact source payload should bypass parsing")

    monkeypatch.setattr(sources, "connect", no_reparse)
    repeated = refresh_official_source(
        "company_tickers", client=client, paths=paths, catalog=catalog
    )

    assert repeated == first
    assert catalog.get_active_source_pointer("company_tickers") == first.cohort_id
    assert not list(paths.cohorts_root.glob(".company_tickers-*"))


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_source_refresh_repairs_missing_or_corrupt_dataset(
    tmp_path: Path, damage: str
) -> None:
    paths = CohortPaths(tmp_path / "artifacts")
    catalog = CohortCatalog(paths)
    raw = tmp_path / "tickers.json"
    raw.write_text(
        '{"0":{"cik_str":10,"ticker":"A","title":"Alpha Inc"}}',
        encoding="utf-8",
    )
    original = publish_tickers_source(raw, paths=paths, catalog=catalog)
    dataset = paths.resolve_relative_path(original.dataset_path)
    if damage == "missing":
        dataset.unlink()
    else:
        dataset.write_bytes(b"corrupt")

    repaired = publish_tickers_source(raw, paths=paths, catalog=catalog)

    assert repaired == original
    assert file_sha256(dataset) == original.dataset_sha256
    assert pq.read_table(dataset).num_rows == original.row_count


def test_refresh_universe_uses_client_and_activates_after_publish(
    tmp_path: Path,
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    session = FakeSession()
    session.register_bytes(
        SOURCE_URLS["cik_lookup"],
        fixture_path("cik_lookup_universe_mini.txt").read_bytes(),
    )

    record = refresh_official_source(
        "cik_lookup", client=build_test_http(session), paths=paths, catalog=catalog
    )

    assert session.calls == [SOURCE_URLS["cik_lookup"]]
    assert resolve_active_source("cik_lookup", catalog=catalog) == record


def test_universe_rejects_partial_source_without_advancing_pointer(
    tmp_path: Path,
) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    session = FakeSession()
    session.register_bytes(SOURCE_URLS["cik_lookup"], b"GOOD CORP:20:\nmalformed\n")

    with pytest.raises(ValueError, match="malformed or out-of-range"):
        refresh_official_source(
            "cik_lookup", client=build_test_http(session), paths=paths, catalog=catalog
        )

    assert catalog.get_active_source_pointer("cik_lookup") is None


def test_ticker_publisher_refuses_bad_rows(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    raw = tmp_path / "tickers.json"
    raw.write_text(
        json.dumps({"0": {"cik_str": 0, "ticker": "X", "title": "Bad"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid CIK"):
        publish_tickers_source(raw, paths=paths, catalog=catalog)


def test_ticker_publisher_handles_single_quote_in_name(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    catalog = CohortCatalog(paths)
    raw = tmp_path / "tickers.json"
    raw.write_text(
        json.dumps(
            {
                "0": {"cik_str": 16732, "ticker": "CPB", "title": "CAMPBELL'S Co"},
            }
        ),
        encoding="utf-8",
    )

    record = publish_tickers_source(raw, paths=paths, catalog=catalog)
    assert record.row_count == 1
    table = pq.read_table(paths.resolve_relative_path(record.dataset_path))
    rows = table.to_pylist()
    assert rows[0]["name"] == "CAMPBELL'S Co"
