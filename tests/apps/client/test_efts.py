"""Tests for the EFTS facade client over the Step 9 probe fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from edgar_sec.apps.client.efts import (
    EftsEndpointError,
    EftsError,
    EftsIntegrityError,
    EftsQuery,
    full_text_search,
    iter_search_pages,
    search_all,
)
from edgar_sec.domain.sec_urls import efts_search_url
from tests.support import load_fixture


class _FakeHttp:
    """Serves a trimmed first-page fixture; later offsets are empty pages."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        if isinstance(self.payload, Exception):
            raise self.payload
        offset = int(parse_qs(urlsplit(url).query)["from"][0])
        if offset == 0 or not isinstance(self.payload, dict):
            return self.payload
        total = self.payload.get("hits", {}).get("total", {})
        return {
            "hits": {"total": total, "hits": []},
            "aggregations": {},
            "query": _echo_for(url),
        }


def _echo_for(url: str) -> dict[str, Any]:
    params = parse_qs(urlsplit(url).query)
    filters: list[dict[str, Any]] = []
    if "forms" in params:
        filters.append({"terms": {"root_forms": params["forms"][0].split(",")}})
    if "ciks" in params:
        filters.append({"terms": {"ciks": params["ciks"][0].split(",")}})
    if "items" in params:
        filters.append({"terms": {"items": params["items"][0].split(",")}})
    return {
        "query": {"bool": {"must": [], "must_not": [], "should": [], "filter": filters}}
    }


def _hit(document_id: str, score: float = 1.0) -> dict[str, Any]:
    accession, _, _filename = document_id.partition(":")
    return {
        "_index": "edgar_file",
        "_id": document_id,
        "_score": score,
        "_source": {
            "adsh": accession,
            "ciks": ["0000320193"],
            "display_names": ["APPLE INC  (AAPL)  (CIK 0000320193)"],
            "form": "10-K",
            "root_forms": ["10-K"],
            "file_date": "2020-01-15",
            "period_ending": "2019-12-31",
            "file_type": "10-K",
            "file_description": "annual report",
            "items": [],
            "sics": ["3571"],
            "biz_states": ["CA"],
            "biz_locations": ["Cupertino, CA"],
            "inc_states": ["CA"],
            "file_num": ["000-10030"],
            "film_num": ["2060001"],
            "sequence": 1,
            "xsl": None,
        },
    }


class _PagedHttp:
    """Synthesizes fixed 100-hit pages for a stated total."""

    def __init__(self, total: int, relation: str = "eq") -> None:
        self.total = total
        self.relation = relation
        self.calls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        params = parse_qs(urlsplit(url).query)
        offset = int(params["from"][0])
        count = max(0, min(100, self.total - offset))
        hits = [_hit(f"0000320193-20-{offset + i:06d}:doc.htm") for i in range(count)]
        return {
            "took": 1,
            "timed_out": False,
            "hits": {
                "total": {"value": self.total, "relation": self.relation},
                "hits": hits,
            },
            "aggregations": {},
            "query": _echo_for(url),
        }


def test_phrase_fixture_maps_hits_and_coverage() -> None:
    client = _FakeHttp(load_fixture("efts/search_phrase.json"))
    result = full_text_search(
        EftsQuery(text='"revenue recognition"', ciks=("320193",)), client=client
    )

    offsets = [parse_qs(urlsplit(c).query)["from"][0] for c in client.calls]
    assert offsets == ["0", "100"]
    params = parse_qs(urlsplit(client.calls[0]).query)
    assert params["q"] == ['"revenue recognition"']
    assert params["ciks"] == ["0000320193"]
    assert params["from"] == ["0"]

    assert result.coverage.total_value == 115
    assert result.coverage.total_relation == "eq"
    assert result.coverage.hits_returned == 3
    assert result.coverage.truncated is True
    first = result.hits[0]
    assert first.document_id == "0001193125-10-012096:dex993.htm"
    assert first.accession == "0001193125-10-012096"
    assert first.filename == "dex993.htm"
    assert first.ciks == ("0000320193",)
    assert first.display_names == ("APPLE INC  (AAPL)  (CIK 0000320193)",)
    assert first.form == "8-K"
    assert first.root_forms == ("8-K",)
    assert first.file_date == "2010-01-25"
    assert first.period_ending == "2010-01-25"
    assert first.items == ("2.02", "9.01")
    assert first.score == pytest.approx(9.001893)
    assert result.hits[1].period_ending is None
    assert result.hits[1].file_description is None


def test_phrase_fixture_aggregations_use_full_result_semantics() -> None:
    client = _FakeHttp(load_fixture("efts/search_phrase.json"))
    result = full_text_search(
        EftsQuery(text='"revenue recognition"', ciks=("320193",)), client=client
    )

    by_name = {agg.name: agg for agg in result.aggregations}
    assert set(by_name) == {
        "entity_filter",
        "sic_filter",
        "biz_states_filter",
        "form_filter",
    }
    assert by_name["sic_filter"].buckets[0].key == "3571"
    assert by_name["sic_filter"].buckets[0].doc_count == 115
    assert by_name["entity_filter"].sum_other_doc_count == 0
    form_counts = {b.key: b.doc_count for b in by_name["form_filter"].buckets}
    assert form_counts["10-Q"] == 63


def test_basic_fixture_reports_the_gte_ceiling() -> None:
    client = _FakeHttp(load_fixture("efts/search_basic.json"))
    result = full_text_search(EftsQuery(text="apple"), client=client)

    assert result.coverage.total_value == 10000
    assert result.coverage.total_relation == "gte"
    assert result.coverage.truncated is True
    by_name = {agg.name: agg for agg in result.aggregations}
    assert len(by_name["entity_filter"].buckets) == 30
    assert by_name["entity_filter"].sum_other_doc_count == 644297


def test_filtered_fixture_verifies_the_items_echo() -> None:
    client = _FakeHttp(load_fixture("efts/search_filtered.json"))
    query = EftsQuery(text="apple", forms=("8-K",), items=("2.02", "7.01"))
    result = full_text_search(query, client=client)

    params = parse_qs(urlsplit(client.calls[0]).query)
    assert params["forms"] == ["8-K"]
    assert params["items"] == ["2.02,7.01"]
    assert result.coverage.total_value == 8819
    assert result.coverage.items_cache_hazard is True
    assert result.hits[0].items == ("2.02", "7.01", "8.01", "9.01")


def test_items_echo_mismatch_is_an_integrity_error() -> None:
    payload = load_fixture("efts/search_filtered.json")

    wrong_items = _FakeHttp(payload)
    with pytest.raises(EftsIntegrityError):
        full_text_search(
            EftsQuery(text="apple", forms=("8-K",), items=("9.99",)),
            client=wrong_items,
        )

    unrequested = _FakeHttp(payload)
    with pytest.raises(EftsIntegrityError):
        full_text_search(EftsQuery(text="apple", forms=("8-K",)), client=unrequested)


@pytest.mark.parametrize(
    "fixture",
    [
        "efts/error_result_window.json",
        "efts/error_blank_search.json",
        "efts/error_bad_date.json",
    ],
)
def test_error_bodies_on_http_200_surface_as_errors(fixture: str) -> None:
    client = _FakeHttp(load_fixture(fixture))
    with pytest.raises(EftsEndpointError):
        full_text_search(EftsQuery(text="apple"), client=client)


def test_query_validation_refuses_unverified_shapes() -> None:
    with pytest.raises(ValueError):
        EftsQuery()
    with pytest.raises(ValueError):
        EftsQuery(text="apple", startdt="2020-01-01")
    with pytest.raises(ValueError):
        EftsQuery(text="apple", startdt="2020-02-01", enddt="2020-01-01")
    with pytest.raises(ValueError):
        EftsQuery(text="apple", sec_syntax="apple")


def test_date_pair_is_sent_explicitly_without_date_range() -> None:
    client = _PagedHttp(total=0)
    full_text_search(
        EftsQuery(text="apple", startdt="2020-01-01", enddt="2020-12-31"),
        client=client,
    )
    params = parse_qs(urlsplit(client.calls[0]).query)
    assert params["startdt"] == ["2020-01-01"]
    assert params["enddt"] == ["2020-12-31"]
    assert "dateRange" not in params


def test_page_iterator_walks_offsets_until_the_total() -> None:
    client = _PagedHttp(total=250)
    pages = list(iter_search_pages(EftsQuery(text="apple"), client=client))

    assert [page.offset for page in pages] == [0, 100, 200]
    assert sum(len(page.hits) for page in pages) == 250
    offsets = [parse_qs(urlsplit(call).query)["from"][0] for call in client.calls]
    assert offsets == ["0", "100", "200"]


def test_page_iterator_stops_at_the_ceiling_without_fetching_past_it() -> None:
    client = _PagedHttp(total=10000, relation="gte")
    result = search_all(EftsQuery(text="risk"), client=client)

    assert result.coverage.hits_returned == 10000
    assert result.coverage.ceiling_reached is True
    assert result.coverage.truncated is True
    offsets = {int(parse_qs(urlsplit(call).query)["from"][0]) for call in client.calls}
    assert max(offsets) == 9900


def test_max_hits_cap_reports_truncation() -> None:
    client = _PagedHttp(total=250)
    result = full_text_search(EftsQuery(text="apple"), client=client, max_hits=150)
    assert result.coverage.hits_returned == 150
    assert result.coverage.truncated is True


class _SlicedHttp:
    """Per-slice totals with one overlapping document across slices."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.slices = {
            ("2020-01-01", "2020-01-31"): ["a", "b"],
            ("2020-02-01", "2020-02-29"): ["b", "c"],
        }
        self._numbers = {"a": 0, "b": 1, "c": 2}

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        params = parse_qs(urlsplit(url).query)
        key = (params["startdt"][0], params["enddt"][0])
        names = self.slices[key]
        hits = [
            _hit(f"0000320193-20-00000{self._numbers[name]}:{name}.htm")
            for name in names
        ]
        return {
            "hits": {
                "total": {"value": len(names), "relation": "eq"},
                "hits": hits,
            },
            "aggregations": {},
            "query": _echo_for(url),
        }


def test_exhaustive_retrieval_date_slices_and_dedupes_by_id() -> None:
    client = _SlicedHttp()
    query = EftsQuery(text="apple", startdt="2020-01-01", enddt="2020-02-29")
    result = search_all(query, client=client, exhaustive=True)

    assert [hit.filename for hit in result.hits] == ["a.htm", "b.htm", "c.htm"]
    assert result.coverage.hits_returned == 3
    assert result.coverage.total_value == 4
    assert result.coverage.truncated is False
    windows = {
        (
            parse_qs(urlsplit(call).query)["startdt"][0],
            parse_qs(urlsplit(call).query)["enddt"][0],
        )
        for call in client.calls
    }
    assert windows == {("2020-01-01", "2020-01-31"), ("2020-02-01", "2020-02-29")}


def test_exhaustive_retrieval_requires_a_date_pair() -> None:
    with pytest.raises(EftsError):
        search_all(EftsQuery(text="apple"), client=_PagedHttp(0), exhaustive=True)


def test_facade_full_text_search_uses_the_injected_client() -> None:
    from edgar_sec.apps.client.facade import Edgar

    http = _FakeHttp(load_fixture("efts/search_phrase.json"))
    facade = Edgar(sec_client=http)  # type: ignore[arg-type]
    result = facade.full_text_search(text='"revenue recognition"', ciks=(320193,))

    assert result.coverage.total_value == 115
    assert len(result.hits) == 3
    assert len(http.calls) == 2


def test_no_store_transport_never_caches_a_search(tmp_path: Path) -> None:
    from edgar_sec.infra.sec_http.client import SecHttpClient
    from edgar_sec.infra.sec_http.rate_limit import RateLimiter
    from edgar_sec.infra.sec_http.retry import RetryPolicy
    from tests.support import FakeSession

    payload = load_fixture("efts/search_phrase.json")
    url = f"{efts_search_url()}?{urlencode([('q', '"revenue recognition"'), ('ciks', '0000320193'), ('from', '0')])}"
    next_url = f"{efts_search_url()}?{urlencode([('q', '"revenue recognition"'), ('ciks', '0000320193'), ('from', '100')])}"
    continuation = {
        "hits": {"total": {"value": 115, "relation": "eq"}, "hits": []},
        "aggregations": {},
        "query": {
            "query": {
                "bool": {
                    "must": [],
                    "must_not": [],
                    "should": [],
                    "filter": [{"terms": {"ciks": ["0000320193"]}}],
                }
            }
        },
    }
    session = FakeSession()
    session.register(url, payload)
    session.register(next_url, continuation)
    client = SecHttpClient(
        user_agent="TestClient/1.0 test@example.com",
        rate_limiter=RateLimiter(min_interval_s=0.001),
        retry_policy=RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0),
        cache_dir=tmp_path,
        session_factory=lambda: session,
    )
    query = EftsQuery(text='"revenue recognition"', ciks=("320193",))

    assert full_text_search(query, client=client).coverage.total_value == 115
    assert full_text_search(query, client=client).coverage.total_value == 115
    assert session.calls == [url, next_url, url, next_url]
    stats = client.cache_stats()
    assert stats is not None
    assert stats["responses_count"] == 0


def test_capture_writes_artefact_with_the_live_hit_set(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    from edgar_sec.apps.client.efts import capture_full_text_search

    query = EftsQuery(text='"revenue recognition"', ciks=("320193",))
    live = full_text_search(
        query, client=_FakeHttp(load_fixture("efts/search_phrase.json"))
    )
    capture = capture_full_text_search(
        query,
        client=_FakeHttp(load_fixture("efts/search_phrase.json")),
        artifacts_root=tmp_path,
    )

    assert capture.directory == tmp_path / "queries" / "efts" / capture.query_hash
    record = json.loads((capture.directory / "query.json").read_text())
    assert record["artefact"] == "efts_query_capture"
    assert record["query"]["ciks"] == ["0000320193"]
    assert record["query_hash"] == capture.query_hash
    assert record["executed_at"] == capture.executed_at
    assert record["coverage"]["total_value"] == 115
    assert record["coverage"]["hits_returned"] == 3
    assert [agg["name"] for agg in record["aggregations"]] == [
        "entity_filter",
        "sic_filter",
        "biz_states_filter",
        "form_filter",
    ]

    table = pq.read_table(capture.directory / "hits.parquet")
    rows = table.to_pylist()
    assert [row["document_id"] for row in rows] == [
        hit.document_id for hit in live.hits
    ]
    assert [row["accession"] for row in rows] == [hit.accession for hit in live.hits]
    assert rows[0]["filename"] == "dex993.htm"
    assert rows[0]["cik"] == "0000320193"
    assert rows[0]["form"] == "8-K"
    assert rows[0]["file_date"] == "2010-01-25"
    assert [i.document_id for i in capture.identities] == [
        hit.document_id for hit in live.hits
    ]


def test_capture_streams_every_page_and_dedupes_when_exhaustive(
    tmp_path: Path,
) -> None:
    import pyarrow.parquet as pq

    from edgar_sec.apps.client.efts import capture_full_text_search

    paged = capture_full_text_search(
        EftsQuery(text="apple"),
        client=_PagedHttp(total=250),
        artifacts_root=tmp_path,
    )
    assert paged.coverage.hits_returned == 250
    assert pq.read_table(paged.directory / "hits.parquet").num_rows == 250

    sliced = capture_full_text_search(
        EftsQuery(text="apple", startdt="2020-01-01", enddt="2020-02-29"),
        client=_SlicedHttp(),
        artifacts_root=tmp_path,
        exhaustive=True,
    )
    assert [i.filename for i in sliced.identities] == ["a.htm", "b.htm", "c.htm"]
    assert pq.read_table(sliced.directory / "hits.parquet").num_rows == 3


def test_plain_search_leaves_the_artifacts_tree_untouched(tmp_path: Path) -> None:
    from edgar_sec.apps.client.facade import Edgar

    http = _FakeHttp(load_fixture("efts/search_phrase.json"))
    facade = Edgar(artifacts_root=tmp_path, sec_client=http)  # type: ignore[arg-type]
    facade.full_text_search(text='"revenue recognition"', ciks=(320193,))
    assert list(tmp_path.iterdir()) == []

    capture = facade.capture_full_text_search(
        EftsQuery(text='"revenue recognition"', ciks=("320193",))
    )
    assert capture.directory.is_dir()
    assert (capture.directory / "query.json").is_file()
    assert (capture.directory / "hits.parquet").is_file()


def test_fixture_payloads_are_json_objects() -> None:
    for name in (
        "search_basic",
        "search_phrase",
        "search_filtered",
        "error_result_window",
        "error_blank_search",
        "error_bad_date",
    ):
        payload = load_fixture(f"efts/{name}.json")
        assert isinstance(payload, dict)
        assert json.dumps(payload)
