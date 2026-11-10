"""Facade series/class lookups and N-MFP resolution over the relation."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.domain.browse_urls import browse_series_url
from edgar_sec.engine.forms.form_nmfp.xml_parser import parse_nmfp_xml
from edgar_sec.engine.index_pages.parser_browse import (
    BrowsePageInput,
    ParsedBrowseSeriesPage,
    parse_browse_series_page,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.series_class import (
    ingest_mf_ticker_payload,
    publish_series_class,
)
from edgar_sec.pipelines.metadata_sync.series_class_browse import (
    ingest_browse_page,
)
from tests.support import fixture_path

_PAYLOAD = json.dumps(
    {
        "fields": ["cik", "seriesId", "classId", "symbol"],
        "data": [
            [2110, "S000000001", "C000000001", "AAA"],
            [2110, "S000000001", "C000000002", "AAB"],
            [3100, "S000000002", "C000000003", "CCC"],
            [2663, "S000008702", "C000023718", "IVMXX"],
            [2663, "S000008702", "C000028786", "VYSXX"],
        ],
    }
).encode()


def _published_root(tmp_path: Path) -> str:
    """A published relation over both layers; the store file is removed."""
    paths = resolve_metadata_paths(tmp_path)
    ingest_mf_ticker_payload(_PAYLOAD, paths)
    page = parse_browse_series_page(
        BrowsePageInput(
            "0000002663",
            browse_series_url(2663),
            fixture_path("browse_edgar_series_0000002663.html").read_bytes(),
        )
    )
    assert isinstance(page, ParsedBrowseSeriesPage)
    ingest_browse_page(page, paths)
    published = publish_series_class(paths)
    assert published.snapshot_id is not None
    paths.series_class_store_file.unlink()
    return published.snapshot_id


class _ExplodingClient:
    """Any HTTP use from a lookup fails the test that installed this."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"lookup attempted HTTP via {name}")


def _edgar(tmp_path: Path) -> Edgar:
    return Edgar(artifacts_root=tmp_path, sec_client=_ExplodingClient())  # type: ignore[arg-type]


def test_lookups_answer_from_the_published_snapshot(tmp_path: Path) -> None:
    snapshot_id = _published_root(tmp_path)
    edgar = _edgar(tmp_path)

    found = edgar.fund_series("S000008702")
    assert found.relation_present is True
    assert found.snapshot_id == snapshot_id
    assert found.series is not None
    assert found.series.cik == "0000002663"
    assert found.series.series_name == "Voya Government Money Market Portfolio"
    assert found.series.layers == ("browse", "tickered")

    file_only = edgar.fund_series("S000000001")
    assert file_only.series is not None
    assert file_only.series.series_name is None
    assert file_only.series.layers == ("tickered",)

    shared = edgar.fund_class("C000023718")
    assert shared.fund_class is not None
    assert shared.fund_class.class_name == "Class I"
    assert shared.fund_class.symbol == "IVMXX"
    assert shared.fund_class.layers == ("browse", "tickered")

    # Browse serves no symbol cell for this class; the ticker file's wins.
    overridden = edgar.fund_class("C000028786")
    assert overridden.fund_class is not None
    assert overridden.fund_class.class_name == "Class S"
    assert overridden.fund_class.symbol == "VYSXX"

    untickered = edgar.fund_class("C000074895")
    assert untickered.fund_class is not None
    assert untickered.fund_class.class_name == "Class S2"
    assert untickered.fund_class.symbol is None
    assert untickered.fund_class.layers == ("browse",)

    file_class = edgar.fund_class("C000000001")
    assert file_class.fund_class is not None
    assert file_class.fund_class.class_name is None
    assert file_class.fund_class.symbol == "AAA"

    classes = edgar.fund_series_classes("S000008702")
    assert [row.class_id for row in classes.classes] == [
        "C000023718",
        "C000028786",
        "C000074895",
        "C000076529",
    ]

    registrant = edgar.fund_registrant_series(2663)
    assert [row.series_id for row in registrant.series] == ["S000008702"]
    assert [
        row.series_id for row in edgar.fund_registrant_series("0000002110").series
    ] == ["S000000001"]

    assert [row.class_id for row in edgar.fund_ticker_classes("IVMXX").classes] == [
        "C000023718"
    ]
    assert [row.class_id for row in edgar.fund_ticker_classes("VYSXX").classes] == [
        "C000028786"
    ]
    assert edgar.fund_ticker_classes("").classes == ()


_CROSS_LISTED_PAYLOAD = json.dumps(
    {
        "fields": ["cik", "seriesId", "classId", "symbol"],
        "data": [
            [1281790, "S000004757", "C000093502", "FNKIX"],
            [1281790, "S000061828", "C000093502", "FNKIX"],
        ],
    }
).encode()


def _published_cross_listed_root(tmp_path: Path) -> str:
    """A published relation whose one class is listed under two series."""
    paths = resolve_metadata_paths(tmp_path)
    ingest_mf_ticker_payload(_CROSS_LISTED_PAYLOAD, paths)
    page = parse_browse_series_page(
        BrowsePageInput(
            "0001281790",
            browse_series_url(1281790),
            fixture_path("browse_edgar_series_0001281790.html").read_bytes(),
        )
    )
    assert isinstance(page, ParsedBrowseSeriesPage)
    ingest_browse_page(page, paths)
    published = publish_series_class(paths)
    assert published.snapshot_id is not None
    paths.series_class_store_file.unlink()
    return published.snapshot_id


def test_cross_listed_class_keeps_every_listing(tmp_path: Path) -> None:
    _published_cross_listed_root(tmp_path)
    edgar = _edgar(tmp_path)

    frank = edgar.fund_series_classes("S000004757")
    assert [row.class_id for row in frank.classes] == [
        "C000012947",
        "C000093501",
        "C000093502",
    ]
    camelot = edgar.fund_series_classes("S000061828")
    assert [row.class_id for row in camelot.classes] == [
        "C000093502",
        "C000200195",
        "C000200196",
    ]

    by_ticker = edgar.fund_ticker_classes("FNKIX")
    assert [(row.class_id, row.series_id) for row in by_ticker.classes] == [
        ("C000093502", "S000004757"),
        ("C000093502", "S000061828"),
    ]
    for row in by_ticker.classes:
        assert row.class_name == "INSTITUTIONAL CLASS"
        assert row.layers == ("browse", "tickered")

    single = edgar.fund_class("C000093502")
    assert single.fund_class is not None
    assert single.fund_class.series_id == "S000004757"
    assert single.fund_class.series_name == "Frank Value Fund"
    assert single.fund_class.symbol == "FNKIX"
    assert single.fund_class.layers == ("browse", "tickered")


def test_misses_are_honest_absence(tmp_path: Path) -> None:
    _published_root(tmp_path)
    edgar = _edgar(tmp_path)

    series = edgar.fund_series("S000999999")
    assert series.series is None
    assert series.relation_present is True
    assert edgar.fund_class("C000999999").fund_class is None
    assert edgar.fund_series_classes("S000999999").classes == ()
    assert edgar.fund_registrant_series(999999).series == ()
    assert edgar.fund_ticker_classes("NOPE").classes == ()


def test_unpublished_relation_is_absence(tmp_path: Path) -> None:
    edgar = _edgar(tmp_path)

    found = edgar.fund_series("S000008702")
    assert found.series is None
    assert found.snapshot_id is None
    assert found.relation_present is False


_NMFP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp3">
  <headerData><submissionType>N-MFP3</submissionType></headerData>
  <formData>
    <generalInfo>
      <reportDate>2025-06-30</reportDate>
      <registrantFullName>VOYA GOVERNMENT MONEY MARKET PORTFOLIO</registrantFullName>
      <cik>{cik}</cik>
      <nameOfSeries>{series_name}</nameOfSeries>
      <leiOfSeries>2549004B125C89JKPS95</leiOfSeries>
      <seriesId>{series_id}</seriesId>
    </generalInfo>
    <classLevelInfo><classId>C000023718</classId></classLevelInfo>
  </formData>
</edgarSubmission>
"""


def _nmfp(cik: str, series_name: str, series_id: str) -> bytes:
    return _NMFP_TEMPLATE.format(
        cik=cik, series_name=series_name, series_id=series_id
    ).encode()


def test_nmfp_series_resolves_to_its_relation_row(tmp_path: Path) -> None:
    snapshot_id = _published_root(tmp_path)
    edgar = _edgar(tmp_path)
    document = parse_nmfp_xml(
        _nmfp("0000002663", "Voya Government Money Market Portfolio", "S000008702")
    )

    resolution = edgar.resolve_nmfp_series(document)

    assert resolution.resolved is True
    assert resolution.relation_present is True
    assert resolution.snapshot_id == snapshot_id
    assert resolution.conflicts == ()
    assert resolution.series is not None
    assert resolution.series.series_name == "Voya Government Money Market Portfolio"
    assert resolution.series.cik == "0000002663"
    assert len(resolution.classes) == 4
    assert resolution.document_series_lei == "2549004B125C89JKPS95"


def test_nmfp_fabricated_id_resolves_to_absence(tmp_path: Path) -> None:
    _published_root(tmp_path)
    edgar = _edgar(tmp_path)
    document = parse_nmfp_xml(_nmfp("0000002663", "Fabricated Fund", "S000999999"))

    resolution = edgar.resolve_nmfp_series(document)

    assert resolution.resolved is False
    assert resolution.series is None
    assert resolution.classes == ()
    assert resolution.conflicts == ()


def test_nmfp_name_disagreement_is_a_reported_conflict(tmp_path: Path) -> None:
    _published_root(tmp_path)
    edgar = _edgar(tmp_path)
    document = parse_nmfp_xml(
        _nmfp("0000002663", "Voya Renamed Portfolio", "S000008702")
    )

    resolution = edgar.resolve_nmfp_series(document)

    assert resolution.resolved is True
    assert len(resolution.conflicts) == 1
    assert resolution.conflicts[0].startswith("series_name:")
    assert resolution.series is not None
    assert resolution.series.series_name == "Voya Government Money Market Portfolio"


def test_nmfp_registrant_disagreement_is_a_reported_conflict(
    tmp_path: Path,
) -> None:
    _published_root(tmp_path)
    edgar = _edgar(tmp_path)
    document = parse_nmfp_xml(
        _nmfp("0000009999", "Voya Government Money Market Portfolio", "S000008702")
    )

    resolution = edgar.resolve_nmfp_series(document)

    assert resolution.resolved is True
    assert len(resolution.conflicts) == 1
    assert resolution.conflicts[0].startswith("registrant_cik:")
