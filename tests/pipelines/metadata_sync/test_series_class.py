"""Series/class tickered leg: field-for-field rows, reconciled counts."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import CohortPaths
from edgar_sec.pipelines.cohort.sources import publish_mf_source
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.series_class import (
    FUND_SERIES_CLASS_SPEC,
    SOURCES_RELATION,
    TICKERED_RELATION,
    TickeredRow,
    ingest_mf_ticker_payload,
    parse_mf_ticker_payload,
    publish_series_class,
    read_tickered_rows,
    series_class_tip,
)
from tests.support import fixture_path

EXPECTED_ROWS = [
    TickeredRow("0000002110", "S000000001", "C000000001", "AAA"),
    TickeredRow("0000002110", "S000000001", "C000000002", "AAB"),
    TickeredRow("0000003100", "S000000002", "C000000003", "CCC"),
]


def _payload() -> bytes:
    return fixture_path("company_tickers_mf_mini.json").read_bytes()


def test_parse_reconciles_with_cohort_origin_metrics() -> None:
    rows, counts = parse_mf_ticker_payload(_payload())

    assert rows == EXPECTED_ROWS
    assert counts.listing_row_count == 3
    assert counts.distinct_series_count == 2
    assert counts.distinct_class_count == 3
    assert counts.distinct_cik_count == 2


def test_parse_rejects_changed_fields_and_bad_rows() -> None:
    document = json.loads(_payload())
    document["fields"] = ["cik", "seriesId", "classId"]
    with pytest.raises(ValueError, match="fields changed"):
        parse_mf_ticker_payload(json.dumps(document).encode())

    document = json.loads(_payload())
    document["data"] = [[2110, "S000000001", "C000000001"]]
    with pytest.raises(ValueError, match="not a 4-field list"):
        parse_mf_ticker_payload(json.dumps(document).encode())


def test_empty_symbol_row_is_kept_field_for_field() -> None:
    document = {
        "fields": ["cik", "seriesId", "classId", "symbol"],
        "data": [[809064, "S000110376", "C000281627", ""]],
    }

    rows, counts = parse_mf_ticker_payload(json.dumps(document).encode())

    assert rows == [TickeredRow("0000809064", "S000110376", "C000281627", "")]
    assert counts.listing_row_count == 1


def test_relation_spec_declares_the_tickered_contract() -> None:
    assert FUND_SERIES_CLASS_SPEC.name == TICKERED_RELATION
    assert FUND_SERIES_CLASS_SPEC.primary_key == ("class_id",)
    assert FUND_SERIES_CLASS_SPEC.merge_strategy == "upsert"
    assert FUND_SERIES_CLASS_SPEC.entity_key == "cik"
    assert FUND_SERIES_CLASS_SPEC.schema.names == [
        "cik",
        "series_id",
        "class_id",
        "symbol",
    ]


def test_ingest_publish_round_trip_and_noops(tmp_path: Path) -> None:
    paths = resolve_metadata_paths(tmp_path)
    assert publish_series_class(paths).published is False

    outcome = ingest_mf_ticker_payload(_payload(), paths)
    assert outcome.already_current is False
    assert outcome.counts.listing_row_count == 3
    assert outcome.counts.distinct_series_count == 2
    assert outcome.counts.distinct_class_count == 3
    assert read_tickered_rows(paths) == EXPECTED_ROWS

    published = publish_series_class(paths)
    assert published.published is True
    assert published.snapshot_id is not None
    assert published.snapshot_id.startswith("series-class-")
    assert published.tip_before is None
    assert series_class_tip(paths) == published.snapshot_id

    part = (
        paths.series_class_snapshots_root
        / published.snapshot_id
        / f"{TICKERED_RELATION}.parquet"
    )
    table = pq.read_table(part)
    assert table.column_names == [
        "cik",
        "series_id",
        "class_id",
        "symbol",
        "source_snapshot_id",
    ]
    published_rows = [
        TickeredRow(row["cik"], row["series_id"], row["class_id"], row["symbol"])
        for row in table.to_pylist()
    ]
    assert published_rows == EXPECTED_ROWS
    assert {row["source_snapshot_id"] for row in table.to_pylist()} == {
        outcome.source_snapshot_id
    }

    catalog = DAGCatalog(paths.series_class_snapshots_root, read_only=True)
    manifest = catalog.get_manifest(published.snapshot_id)
    assert manifest is not None
    assert manifest.metadata["source_name"] == "company_tickers_mf"
    assert manifest.metadata["source_snapshot_id"] == outcome.source_snapshot_id
    assert set(manifest.relations) == {TICKERED_RELATION, SOURCES_RELATION}
    assert manifest.relations[TICKERED_RELATION][0].row_count == 3
    assert manifest.relations[SOURCES_RELATION][0].row_count == 1

    again = ingest_mf_ticker_payload(_payload(), paths)
    assert again.already_current is True
    republished = publish_series_class(paths)
    assert republished.published is False
    assert republished.tip_before == published.snapshot_id


def test_leg_keys_beside_cohort_and_leaves_its_artifact_unchanged(
    tmp_path: Path,
) -> None:
    cohort_paths = CohortPaths(tmp_path / "cohort")
    catalog = CohortCatalog(cohort_paths)
    record = publish_mf_source(
        fixture_path("company_tickers_mf_mini.json"),
        paths=cohort_paths,
        catalog=catalog,
    )
    dataset = cohort_paths.resolve_relative_path(record.dataset_path)
    before = file_sha256(dataset)
    details = json.loads(record.origin_json)

    paths = resolve_metadata_paths(tmp_path / "metadata")
    outcome = ingest_mf_ticker_payload(_payload(), paths)
    publish_series_class(paths)

    assert outcome.source_snapshot_id == details["source_snapshot_id"]
    assert outcome.counts.listing_row_count == details["listing_row_count"]
    assert outcome.counts.distinct_series_count == details["distinct_series_count"]
    assert outcome.counts.distinct_class_count == details["distinct_class_count"]
    assert file_sha256(dataset) == before
