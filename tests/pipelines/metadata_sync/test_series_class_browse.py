"""Series/class browse leg: spec contract and per-registrant ingest."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.domain.browse_urls import browse_series_url
from edgar_sec.engine.index_pages.parser_browse import (
    BrowseClassRow,
    BrowseDiagnostics,
    BrowseSeriesRow,
    ParsedBrowseSeriesPage,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.series_class_browse import (
    BROWSE_RELATION,
    BROWSE_SERIES_RELATION,
    FUND_SERIES_CLASS_BROWSE_SERIES_SPEC,
    FUND_SERIES_CLASS_BROWSE_SPEC,
    BrowseSeriesRelationRow,
    ingest_browse_page,
    read_browse_rows,
    read_browse_series_rows,
)


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


def test_browse_specs_declare_the_browse_contract() -> None:
    assert FUND_SERIES_CLASS_BROWSE_SPEC.name == BROWSE_RELATION
    assert FUND_SERIES_CLASS_BROWSE_SPEC.primary_key == ("series_id", "class_id")
    assert FUND_SERIES_CLASS_BROWSE_SPEC.merge_strategy == "upsert"
    assert FUND_SERIES_CLASS_BROWSE_SPEC.entity_key == "cik"
    assert FUND_SERIES_CLASS_BROWSE_SPEC.schema.names == [
        "cik",
        "series_id",
        "series_name",
        "class_id",
        "class_name",
        "symbol",
        "source_url",
        "page_sha256",
    ]
    assert FUND_SERIES_CLASS_BROWSE_SERIES_SPEC.name == BROWSE_SERIES_RELATION
    assert FUND_SERIES_CLASS_BROWSE_SERIES_SPEC.primary_key == ("series_id",)
    assert FUND_SERIES_CLASS_BROWSE_SERIES_SPEC.schema.names == [
        "cik",
        "series_id",
        "series_name",
        "source_url",
        "page_sha256",
    ]


def test_browse_ingest_replaces_only_its_registrant(tmp_path: Path) -> None:
    paths = resolve_metadata_paths(tmp_path)
    page_a = _page(
        "0000002110",
        "a" * 64,
        (BrowseSeriesRow("S000000001", "Fund One"),),
        (
            BrowseClassRow("S000000001", "C000000001", "Fund One A", "AAA"),
            BrowseClassRow("S000000001", "C000000002", "Fund One B", None),
        ),
    )
    page_b = _page(
        "0000003100",
        "b" * 64,
        (BrowseSeriesRow("S000000002", "Fund Two"),),
        (BrowseClassRow("S000000002", "C000000003", "Fund Two A", "CCC"),),
    )
    ingest_browse_page(page_a, paths)
    ingest_browse_page(page_b, paths)
    revised = _page(
        "0000002110",
        "d" * 64,
        (BrowseSeriesRow("S000000001", "Fund One"),),
        (BrowseClassRow("S000000001", "C000000001", "Fund One A", "AAA"),),
    )

    outcome = ingest_browse_page(revised, paths)

    assert outcome.already_current is False
    assert ingest_browse_page(revised, paths).already_current is True
    rows = read_browse_rows(paths)
    assert [row.class_id for row in rows] == ["C000000001", "C000000003"]
    assert rows[0].page_sha256 == "d" * 64
    assert rows[1].page_sha256 == "b" * 64
    assert rows[1].symbol == "CCC"
    assert read_browse_series_rows(paths) == [
        BrowseSeriesRelationRow(
            "0000002110", "S000000001", "Fund One", browse_series_url(2110), "d" * 64
        ),
        BrowseSeriesRelationRow(
            "0000003100", "S000000002", "Fund Two", browse_series_url(3100), "b" * 64
        ),
    ]


def test_browse_ingest_stores_a_cross_listed_class_under_both_series(
    tmp_path: Path,
) -> None:
    paths = resolve_metadata_paths(tmp_path)
    page = _page(
        "0001281790",
        "e" * 64,
        (
            BrowseSeriesRow("S000004757", "Frank Value Fund"),
            BrowseSeriesRow("S000061828", "Camelot Event Driven Fund"),
        ),
        (
            BrowseClassRow("S000004757", "C000093502", "INSTITUTIONAL CLASS", "FNKIX"),
            BrowseClassRow("S000061828", "C000093502", "INSTITUTIONAL CLASS", "FNKIX"),
        ),
    )

    outcome = ingest_browse_page(page, paths)

    assert outcome.class_count == 2
    assert ingest_browse_page(page, paths).already_current is True
    rows = read_browse_rows(paths)
    assert [(row.series_id, row.class_id) for row in rows] == [
        ("S000004757", "C000093502"),
        ("S000061828", "C000093502"),
    ]
    assert [row.series_name for row in rows] == [
        "Frank Value Fund",
        "Camelot Event Driven Fund",
    ]
