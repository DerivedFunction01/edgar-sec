"""Series/class tickered leg: field-for-field rows, reconciled counts."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.browse_urls import browse_series_url
from edgar_sec.engine.index_pages.parser_browse import (
    BrowseClassRow,
    BrowseDiagnostics,
    BrowsePageInput,
    BrowseSeriesRow,
    ParsedBrowseSeriesPage,
    parse_browse_series_page,
)
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
    reconcile_series_class,
    series_class_part_paths,
    series_class_tip,
)
from edgar_sec.pipelines.metadata_sync.series_class_browse import (
    BROWSE_RELATION,
    BROWSE_SERIES_RELATION,
    BrowseRelationRow,
    BrowseSeriesRelationRow,
    ingest_browse_page,
    read_browse_rows,
    read_browse_series_rows,
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


def _page(
    cik: str,
    sha: str,
    series: tuple[BrowseSeriesRow, ...],
    classes: tuple[BrowseClassRow, ...],
) -> ParsedBrowseSeriesPage:
    return ParsedBrowseSeriesPage(
        cik=cik,
        source_url=browse_series_url(cik),
        page_sha256=sha,
        registrant_name="Registrant",
        declared_item_count=len(series) + len(classes),
        series=series,
        classes=classes,
        diagnostics=BrowseDiagnostics(()),
    )


_PAGE_A = _page(
    "0000002110",
    "a" * 64,
    (BrowseSeriesRow("S000000001", "Fund One"),),
    (
        BrowseClassRow("S000000001", "C000000001", "Fund One Class A", "AAA"),
        BrowseClassRow("S000000001", "C000000002", "Fund One Class B", None),
        BrowseClassRow("S000000001", "C000000009", "Fund One Class C", "NEW"),
    ),
)
_PAGE_B = _page(
    "0000003100",
    "b" * 64,
    (
        BrowseSeriesRow("S000000002", "Fund Two"),
        BrowseSeriesRow("S000000008", "Fund Eight"),
    ),
    (BrowseClassRow("S000000002", "C000000003", "Fund Two Class A", "CCC"),),
)

EXPECTED_BROWSE_ROWS = [
    BrowseRelationRow(
        "0000002110",
        "S000000001",
        "Fund One",
        "C000000001",
        "Fund One Class A",
        "AAA",
        browse_series_url(2110),
        "a" * 64,
    ),
    BrowseRelationRow(
        "0000002110",
        "S000000001",
        "Fund One",
        "C000000002",
        "Fund One Class B",
        None,
        browse_series_url(2110),
        "a" * 64,
    ),
    BrowseRelationRow(
        "0000002110",
        "S000000001",
        "Fund One",
        "C000000009",
        "Fund One Class C",
        "NEW",
        browse_series_url(2110),
        "a" * 64,
    ),
    BrowseRelationRow(
        "0000003100",
        "S000000002",
        "Fund Two",
        "C000000003",
        "Fund Two Class A",
        "CCC",
        browse_series_url(3100),
        "b" * 64,
    ),
]


def test_reconcile_on_an_empty_store_is_all_zeroes(tmp_path: Path) -> None:
    paths = resolve_metadata_paths(tmp_path)

    result = reconcile_series_class(paths)

    assert result.series_in_both == 0
    assert result.classes_in_both == 0
    assert result.symbol_agreements == 0
    assert read_browse_rows(paths) == []


def test_browse_ingest_reconcile_and_publish(tmp_path: Path) -> None:
    paths = resolve_metadata_paths(tmp_path)
    ingest_mf_ticker_payload(_payload(), paths)

    first = ingest_browse_page(_PAGE_A, paths)
    assert first.already_current is False
    assert first.series_count == 1
    assert first.class_count == 3
    ingest_browse_page(_PAGE_B, paths)
    assert ingest_browse_page(_PAGE_A, paths).already_current is True
    assert read_browse_rows(paths) == EXPECTED_BROWSE_ROWS
    assert read_browse_series_rows(paths) == [
        BrowseSeriesRelationRow(
            "0000002110", "S000000001", "Fund One", browse_series_url(2110), "a" * 64
        ),
        BrowseSeriesRelationRow(
            "0000003100", "S000000002", "Fund Two", browse_series_url(3100), "b" * 64
        ),
        BrowseSeriesRelationRow(
            "0000003100",
            "S000000008",
            "Fund Eight",
            browse_series_url(3100),
            "b" * 64,
        ),
    ]

    result = reconcile_series_class(paths)
    assert result.series_in_both == 2
    assert result.series_browse_only == 1
    assert result.series_file_only == 0
    assert result.classes_in_both == 3
    assert result.classes_browse_only == 1
    assert result.classes_file_only == 0
    assert result.symbol_agreements == 2
    assert result.symbol_disagreements == 0
    assert result.shared_classes_browse_untickered == 1

    published = publish_series_class(paths)
    assert published.published is True
    part = (
        paths.series_class_snapshots_root
        / published.snapshot_id
        / f"{BROWSE_RELATION}.parquet"
    )
    table = pq.read_table(part)
    assert table.column_names == [
        "cik",
        "series_id",
        "series_name",
        "class_id",
        "class_name",
        "symbol",
        "source_url",
        "page_sha256",
    ]
    assert table.num_rows == 4
    published_rows = [
        BrowseRelationRow(
            row["cik"],
            row["series_id"],
            row["series_name"],
            row["class_id"],
            row["class_name"],
            row["symbol"],
            row["source_url"],
            row["page_sha256"],
        )
        for row in table.to_pylist()
    ]
    assert published_rows == EXPECTED_BROWSE_ROWS

    catalog = DAGCatalog(paths.series_class_snapshots_root, read_only=True)
    manifest = catalog.get_manifest(published.snapshot_id)
    assert manifest is not None
    assert set(manifest.relations) == {
        TICKERED_RELATION,
        SOURCES_RELATION,
        BROWSE_RELATION,
        BROWSE_SERIES_RELATION,
    }
    assert manifest.relations[BROWSE_RELATION][0].row_count == 4
    assert manifest.relations[BROWSE_SERIES_RELATION][0].row_count == 3

    republished = publish_series_class(paths)
    assert republished.published is False
    assert republished.tip_before == published.snapshot_id


def test_browse_symbol_disagreement_is_counted(tmp_path: Path) -> None:
    paths = resolve_metadata_paths(tmp_path)
    ingest_mf_ticker_payload(_payload(), paths)
    page = _page(
        "0000002110",
        "c" * 64,
        (BrowseSeriesRow("S000000001", "Fund One"),),
        (BrowseClassRow("S000000001", "C000000001", "Fund One Class A", "ZZZ"),),
    )
    ingest_browse_page(page, paths)

    result = reconcile_series_class(paths)

    assert result.classes_in_both == 1
    assert result.symbol_agreements == 0
    assert result.symbol_disagreements == 1


def test_specimen_page_reconciles_against_the_file_layer(
    tmp_path: Path,
) -> None:
    raw = fixture_path("browse_edgar_series_0000002663.html").read_bytes()
    page = parse_browse_series_page(
        BrowsePageInput("0000002663", browse_series_url(2663), raw)
    )
    assert isinstance(page, ParsedBrowseSeriesPage)
    payload = json.dumps(
        {
            "fields": ["cik", "seriesId", "classId", "symbol"],
            "data": [
                [2663, "S000008702", "C000023718", "IVMXX"],
                [9999, "S000000099", "C000000099", "ZZZ"],
            ],
        }
    ).encode()

    paths = resolve_metadata_paths(tmp_path)
    ingest_mf_ticker_payload(payload, paths)
    outcome = ingest_browse_page(page, paths)

    assert outcome.series_count == 1
    assert outcome.class_count == 4
    result = reconcile_series_class(paths)
    assert result.series_in_both == 1
    assert result.series_browse_only == 0
    assert result.series_file_only == 1
    assert result.classes_in_both == 1
    assert result.classes_browse_only == 3
    assert result.classes_file_only == 1
    assert result.symbol_agreements == 1
    assert result.symbol_disagreements == 0
    rows = read_browse_rows(paths)
    assert {row.symbol for row in rows} == {"IVMXX", None}
    assert {row.series_name for row in rows} == {
        "Voya Government Money Market Portfolio"
    }
    assert {row.class_name for row in rows} == {
        "Class I",
        "Class S",
        "Class S2",
        "Class ADV",
    }


def test_part_paths_name_the_tip_snapshots_own_parts(tmp_path: Path) -> None:
    paths = resolve_metadata_paths(tmp_path)
    ingest_mf_ticker_payload(_payload(), paths)
    published = publish_series_class(paths)
    assert published.snapshot_id is not None

    assert series_class_part_paths(paths, "series-class-absent") == {}
    parts = series_class_part_paths(paths, published.snapshot_id)

    assert set(parts) == {TICKERED_RELATION, SOURCES_RELATION}
    for relation, relation_parts in parts.items():
        assert relation_parts == (
            paths.series_class_snapshots_root
            / published.snapshot_id
            / f"{relation}.parquet",
        )
