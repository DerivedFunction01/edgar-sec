"""Facade classified tables: the fast path over context production."""

from __future__ import annotations

from dataclasses import replace

from edgar_sec.apps.client.classified_tables import (
    ORIGIN_FAST,
    build_stamp,
    cache_kind,
    classified_tables_fast,
)
from edgar_sec.apps.client.content_cache import ContentCache
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.forms.cover.profiles import get_profile
from edgar_sec.engine.tables.extraction.profiles import PROFILES, registry_state

_HTML_10K = b"""<html><body>
<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
<p>FORM 10-K</p>
<p>ACME CORPORATION</p>
<p>PART I</p>
<p>ITEM 1. BUSINESS</p>
<p>Acme is a leading provider of widgets.</p>
<table><tr><td>Cash</td><td>100</td></tr><tr><td>Total assets</td><td>500</td></tr></table>
<p>SIGNATURES</p>
<p>Pursuant to the requirements of Section 13 of the Act, signed below.</p>
<table><tr><td>/s/ Jane Doe</td><td>Chief Executive Officer</td></tr></table>
</body></html>"""


def _filing() -> FilingAggregate:
    return FilingAggregate(
        accession=AccessionNumber.from_any("0000000000-24-000001"),
        primary_cik=Cik(1),
        ciks=(Cik(1),),
        form="10-K",
        filing_date="2024-03-01",
        primary_document_path="acme.htm",
        fetcher=lambda filing: _HTML_10K,
    )


def test_fast_path_classifies_and_caches() -> None:
    cache = ContentCache(64 * 1024 * 1024)
    filing = _filing()
    rows = classified_tables_fast(cache, filing)
    assert rows
    assert all(row.source_document == "primary" for row in rows)
    closing = rows[-1]
    assert closing.tier == "genre_refusal"
    assert closing.family == "other"
    again = classified_tables_fast(cache, filing)
    assert again == rows
    assert len(cache) == 1


def test_fast_path_rows_carry_origin_and_stamp() -> None:
    cache = ContentCache(64 * 1024 * 1024)
    rows = classified_tables_fast(cache, _filing())
    version = get_profile("10-K").version
    expected = build_stamp(normalize_version=version, renderer_version=version)
    assert rows
    assert all(row.origin == ORIGIN_FAST for row in rows)
    assert all(row.stamp == expected for row in rows)
    assert expected.startswith("classified-v1;registry=")
    assert "sha256:" not in expected


def test_registry_state_tracks_registry_data() -> None:
    state = registry_state()
    assert state.startswith("sha256:")
    assert registry_state(profiles=PROFILES[:-1]) != state
    altered = (replace(PROFILES[0], family="altered_family"), *PROFILES[1:])
    assert registry_state(profiles=altered) != state


def test_cache_kind_is_stamped_and_stratum_scoped() -> None:
    primary = cache_kind(normalize_version="v1", stratum=None)
    annual = cache_kind(normalize_version="v1", stratum="B")
    assert primary != annual
    assert registry_state() in primary
    assert cache_kind(normalize_version="v2", stratum=None) != primary


def test_stratum_calls_keep_separate_cache_entries() -> None:
    cache = ContentCache(64 * 1024 * 1024)
    filing = _filing()
    primary_rows = classified_tables_fast(cache, filing)
    annual_rows = classified_tables_fast(cache, filing, stratum="B")
    assert len(cache) == 2
    assert [(r.family, r.tier, r.score) for r in annual_rows] == [
        (r.family, r.tier, r.score) for r in primary_rows
    ]
    assert classified_tables_fast(cache, filing) == primary_rows
    assert classified_tables_fast(cache, filing, stratum="B") == annual_rows
    assert len(cache) == 2


def test_cached_products_carry_table_geometries() -> None:
    cache = ContentCache(64 * 1024 * 1024)
    filing = _filing()
    classified_tables_fast(cache, filing)
    kind = cache_kind(normalize_version=get_profile("10-K").version, stratum=None)
    cached = cache.get((kind, filing.accession.value))
    assert cached is not None
    contexts = cached.production.contexts
    assert contexts
    assert all(context.geometry.rows for context in contexts)


def test_fast_path_empty_when_no_payload() -> None:
    cache = ContentCache(64 * 1024 * 1024)
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000000000-24-000002"),
        primary_cik=Cik(1),
        ciks=(Cik(1),),
        form="10-K",
        filing_date="2024-03-01",
    )
    assert classified_tables_fast(cache, filing) == ()
