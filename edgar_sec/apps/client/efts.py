"""EFTS full-text search: a live facade client over the SEC search index.

Only probe-verified query modes and filters are exposed. Hits are
documents, not filings; no text excerpt is served or invented, and
past-ceiling retrieval is an explicit date-sliced option.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from edgar_sec.domain.identity import Cik
from edgar_sec.domain.sec_urls import efts_search_url

__all__ = [
    "EftsAggregation",
    "EftsBucket",
    "EftsCoverage",
    "EftsEndpointError",
    "EftsError",
    "EftsHit",
    "EftsIntegrityError",
    "EftsPage",
    "EftsQuery",
    "EftsSearchResult",
    "full_text_search",
    "iter_search_pages",
    "search_all",
]

PAGE_SIZE = 100
RESULT_WINDOW = 10_000

_AGGREGATIONS = ("entity_filter", "sic_filter", "biz_states_filter", "form_filter")


class EftsError(Exception):
    """Base for EFTS client refusals and endpoint failures."""


class EftsEndpointError(EftsError):
    """The endpoint returned an error body, including on HTTP 200."""


class EftsIntegrityError(EftsError):
    """The response does not match the request it claims to answer."""


@dataclass(frozen=True, slots=True)
class EftsQuery:
    """One EFTS query in the probe-verified surface only.

    ``text`` is read exactly as the endpoint reads it; dates are an
    explicit pair, and a lone bound is refused rather than ignored.
    """

    text: str = ""
    forms: tuple[str, ...] = ()
    ciks: tuple[str, ...] = ()
    items: tuple[str, ...] = ()
    startdt: str | None = None
    enddt: str | None = None
    sec_syntax: str | None = None

    def __post_init__(self) -> None:
        if self.sec_syntax is not None and self.text:
            raise ValueError("pass either text or sec_syntax, not both")
        if not self.query_text and not self.forms and not self.ciks:
            raise ValueError(
                "a query needs text, forms, or ciks; a blank search is refused"
            )
        if (self.startdt is None) != (self.enddt is None):
            raise ValueError("startdt and enddt must be supplied as a pair")
        if self.startdt is not None and self.enddt is not None:
            start = date.fromisoformat(self.startdt)
            end = date.fromisoformat(self.enddt)
            if end < start:
                raise ValueError("enddt precedes startdt")
        object.__setattr__(
            self, "ciks", tuple(_normalize_cik(cik) for cik in self.ciks)
        )
        object.__setattr__(self, "forms", tuple(str(f) for f in self.forms))
        object.__setattr__(self, "items", tuple(str(i) for i in self.items))

    @property
    def query_text(self) -> str:
        """The ``q`` value sent: typed text, or labelled SEC syntax verbatim."""
        return self.sec_syntax if self.sec_syntax is not None else self.text


@dataclass(frozen=True, slots=True)
class EftsHit:
    """One document hit; ``document_id`` is the endpoint's raw ``_id``."""

    document_id: str
    accession: str
    filename: str
    score: float | None
    ciks: tuple[str, ...]
    display_names: tuple[str, ...]
    form: str
    root_forms: tuple[str, ...]
    file_date: str
    period_ending: str | None
    file_type: str
    file_description: str | None
    items: tuple[str, ...]
    sics: tuple[str, ...]
    biz_states: tuple[str, ...]
    biz_locations: tuple[str, ...]
    inc_states: tuple[str, ...]
    file_num: tuple[str, ...]
    film_num: tuple[str, ...]
    sequence: int | None
    xsl: str | None


@dataclass(frozen=True, slots=True)
class EftsBucket:
    """One aggregation bucket over the full, uncapped result set."""

    key: str
    doc_count: int


@dataclass(frozen=True, slots=True)
class EftsAggregation:
    """One verified aggregation: at most 30 buckets plus the remainder."""

    name: str
    buckets: tuple[EftsBucket, ...]
    sum_other_doc_count: int


@dataclass(frozen=True, slots=True)
class EftsCoverage:
    """What a retrieval actually covered, including why it stopped."""

    total_value: int
    total_relation: str
    hits_returned: int
    truncated: bool
    ceiling_reached: bool = False
    items_cache_hazard: bool = False


@dataclass(frozen=True, slots=True)
class EftsPage:
    """One fixed 100-hit page plus its totals and aggregations."""

    hits: tuple[EftsHit, ...]
    offset: int
    total_value: int
    total_relation: str
    aggregations: tuple[EftsAggregation, ...] = ()


@dataclass(frozen=True, slots=True)
class EftsSearchResult:
    """A bounded retrieval: the hits fetched and their coverage block."""

    hits: tuple[EftsHit, ...]
    coverage: EftsCoverage
    aggregations: tuple[EftsAggregation, ...] = ()


def _normalize_cik(raw: str | int | Cik) -> str:
    cik = raw if isinstance(raw, Cik) else Cik.from_raw(raw)
    return cik.to_10digit()


def _str_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    if value is None:
        return ()
    return (str(value),)


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _page_url(query: EftsQuery, offset: int) -> str:
    params: list[tuple[str, str]] = []
    if query.query_text:
        params.append(("q", query.query_text))
    if query.forms:
        params.append(("forms", ",".join(query.forms)))
    if query.ciks:
        params.append(("ciks", ",".join(query.ciks)))
    if query.items:
        params.append(("items", ",".join(query.items)))
    if query.startdt is not None and query.enddt is not None:
        params.append(("startdt", query.startdt))
        params.append(("enddt", query.enddt))
    params.append(("from", str(offset)))
    return f"{efts_search_url()}?{urlencode(params)}"


def _raise_for_error_body(payload: dict[str, Any], url: str) -> None:
    error = payload.get("error")
    if isinstance(error, str) and error:
        raise EftsEndpointError(f"EFTS error for {url}: {error}")
    error_type = payload.get("errorType")
    if error_type:
        message = payload.get("errorMessage", "")
        raise EftsEndpointError(f"EFTS {error_type} for {url}: {message}".rstrip(": "))


def _echoed_items_filter(payload: dict[str, Any]) -> tuple[str, ...] | None:
    """The ``items`` terms filter in the echoed query, or None when absent."""
    echo = payload.get("query")
    if not isinstance(echo, dict):
        return None
    nested = echo.get("query")
    bool_node = nested.get("bool") if isinstance(nested, dict) else echo.get("bool")
    if not isinstance(bool_node, dict):
        return None
    filters = bool_node.get("filter")
    if not isinstance(filters, list):
        return None
    for entry in filters:
        if not isinstance(entry, dict):
            continue
        terms = entry.get("terms")
        if isinstance(terms, dict) and "items" in terms:
            return _str_tuple(terms["items"])
    return None


def _verify_items_echo(query: EftsQuery, payload: dict[str, Any], url: str) -> None:
    """Refuse a replayed response whose echoed items filter is not ours.

    The endpoint's edge cache key omits ``items``, so a response can be
    another query's replay; the echoed filter is the only ground truth.
    """
    echoed = _echoed_items_filter(payload)
    if query.items:
        if echoed is None or set(echoed) != set(query.items):
            raise EftsIntegrityError(
                "EFTS response echo does not carry the requested items "
                f"filter {sorted(query.items)} (echo: "
                f"{sorted(echoed) if echoed is not None else None}); the "
                "endpoint's edge cache omits items from its key, so this "
                f"response may be another query's replay: {url}"
            )
    elif echoed:
        raise EftsIntegrityError(
            "EFTS response echo carries an items filter that was never "
            f"requested {sorted(echoed)}; the endpoint's edge cache omits "
            f"items from its key, so this response is another query's "
            f"replay: {url}"
        )


def _parse_hit(raw: Any) -> EftsHit | None:
    if not isinstance(raw, dict):
        return None
    document_id = str(raw.get("_id", ""))
    source = raw.get("_source")
    if not isinstance(source, dict):
        source = {}
    accession, _, filename = document_id.partition(":")
    adsh = source.get("adsh")
    if isinstance(adsh, str) and adsh:
        accession = adsh
    score = raw.get("_score")
    sequence = source.get("sequence")
    return EftsHit(
        document_id=document_id,
        accession=accession,
        filename=filename,
        score=float(score) if isinstance(score, (int, float)) else None,
        ciks=_str_tuple(source.get("ciks")),
        display_names=_str_tuple(source.get("display_names")),
        form=str(source.get("form", "")),
        root_forms=_str_tuple(source.get("root_forms")),
        file_date=str(source.get("file_date", "")),
        period_ending=_str_or_none(source.get("period_ending")),
        file_type=str(source.get("file_type", "")),
        file_description=_str_or_none(source.get("file_description")),
        items=_str_tuple(source.get("items")),
        sics=_str_tuple(source.get("sics")),
        biz_states=_str_tuple(source.get("biz_states")),
        biz_locations=_str_tuple(source.get("biz_locations")),
        inc_states=_str_tuple(source.get("inc_states")),
        file_num=_str_tuple(source.get("file_num")),
        film_num=_str_tuple(source.get("film_num")),
        sequence=sequence if isinstance(sequence, int) else None,
        xsl=_str_or_none(source.get("xsl")),
    )


def _parse_aggregations(payload: dict[str, Any]) -> tuple[EftsAggregation, ...]:
    raw_aggs = payload.get("aggregations")
    if not isinstance(raw_aggs, dict):
        return ()
    parsed: list[EftsAggregation] = []
    for name in _AGGREGATIONS:
        raw = raw_aggs.get(name)
        if not isinstance(raw, dict):
            continue
        buckets: list[EftsBucket] = []
        raw_buckets = raw.get("buckets")
        if isinstance(raw_buckets, list):
            for bucket in raw_buckets:
                if not isinstance(bucket, dict):
                    continue
                count = bucket.get("doc_count")
                buckets.append(
                    EftsBucket(
                        key=str(bucket.get("key", "")),
                        doc_count=count if isinstance(count, int) else 0,
                    )
                )
        other = raw.get("sum_other_doc_count")
        parsed.append(
            EftsAggregation(
                name=name,
                buckets=tuple(buckets),
                sum_other_doc_count=other if isinstance(other, int) else 0,
            )
        )
    return tuple(parsed)


def _fetch_page(query: EftsQuery, offset: int, *, client: Any) -> EftsPage:
    url = _page_url(query, offset)
    payload = client.get_json(url)
    if not isinstance(payload, dict):
        raise EftsEndpointError(f"EFTS returned a non-object body for {url}")
    _raise_for_error_body(payload, url)
    _verify_items_echo(query, payload, url)
    hits_node = payload.get("hits")
    if not isinstance(hits_node, dict):
        raise EftsEndpointError(f"EFTS response has no hits object for {url}")
    total = hits_node.get("total")
    if isinstance(total, dict):
        value = total.get("value")
        total_value = value if isinstance(value, int) else 0
        total_relation = str(total.get("relation", "eq"))
    else:
        total_value, total_relation = 0, "eq"
    raw_hits = hits_node.get("hits")
    hits = (
        tuple(hit for hit in (_parse_hit(raw) for raw in raw_hits) if hit is not None)
        if isinstance(raw_hits, list)
        else ()
    )
    return EftsPage(
        hits=hits,
        offset=offset,
        total_value=total_value,
        total_relation=total_relation,
        aggregations=_parse_aggregations(payload),
    )


def iter_search_pages(
    query: EftsQuery,
    *,
    client: Any,
    max_hits: int | None = None,
) -> Iterator[EftsPage]:
    """Yield pages of 100 hits until the reported total or the ceiling.

    A page at or past the 10,000-hit window is never issued: the walk
    stops at the ceiling so the caller can report truncation.
    """
    if max_hits is not None and max_hits < 0:
        raise ValueError("max_hits must be non-negative")
    offset = 0
    returned = 0
    while offset < RESULT_WINDOW:
        if max_hits is not None and returned >= max_hits:
            return
        page = _fetch_page(query, offset, client=client)
        if max_hits is not None and len(page.hits) > max_hits - returned:
            yield replace(page, hits=page.hits[: max_hits - returned])
            return
        yield page
        returned += len(page.hits)
        offset += PAGE_SIZE
        if not page.hits:
            return
        if page.total_relation == "eq" and offset >= page.total_value:
            return


def full_text_search(
    query: EftsQuery,
    *,
    client: Any,
    max_hits: int | None = None,
) -> EftsSearchResult:
    """Run one bounded search: a single page by default.

    ``max_hits`` walks further pages; the coverage block states the
    reported total, hits returned, and any cap/ceiling truncation.
    """
    cap = PAGE_SIZE if max_hits is None else max_hits
    hits: list[EftsHit] = []
    aggregations: tuple[EftsAggregation, ...] = ()
    total_value, total_relation = 0, "eq"
    for page in iter_search_pages(query, client=client, max_hits=cap):
        if not aggregations:
            aggregations = page.aggregations
        total_value, total_relation = page.total_value, page.total_relation
        hits.extend(page.hits)
    returned = len(hits)
    truncated = total_relation == "gte" or returned < total_value
    return EftsSearchResult(
        hits=tuple(hits),
        coverage=EftsCoverage(
            total_value=total_value,
            total_relation=total_relation,
            hits_returned=returned,
            truncated=truncated,
            ceiling_reached=returned >= RESULT_WINDOW,
            items_cache_hazard=bool(query.items),
        ),
        aggregations=aggregations,
    )


def _month_slices(start: date, end: date) -> Iterator[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        slice_end = min(end, next_month - timedelta(days=1))
        yield cursor, slice_end
        cursor = next_month


def search_all(
    query: EftsQuery,
    *,
    client: Any,
    exhaustive: bool = False,
) -> EftsSearchResult:
    """Collect a full retrieval, date-sliced past the ceiling on request.

    Without ``exhaustive`` the walk stops at the ceiling and reports
    truncation; with it, months are walked and hits dedupe by ``_id``.
    """
    if not exhaustive:
        hits: list[EftsHit] = []
        aggregations: tuple[EftsAggregation, ...] = ()
        total_value, total_relation = 0, "eq"
        for page in iter_search_pages(query, client=client):
            if not aggregations:
                aggregations = page.aggregations
            total_value, total_relation = page.total_value, page.total_relation
            hits.extend(page.hits)
        returned = len(hits)
        return EftsSearchResult(
            hits=tuple(hits),
            coverage=EftsCoverage(
                total_value=total_value,
                total_relation=total_relation,
                hits_returned=returned,
                truncated=total_relation == "gte",
                ceiling_reached=total_relation == "gte" and returned >= RESULT_WINDOW,
                items_cache_hazard=bool(query.items),
            ),
            aggregations=aggregations,
        )
    if query.startdt is None or query.enddt is None:
        raise EftsError(
            "exhaustive retrieval past the ceiling requires an explicit "
            "startdt/enddt pair to slice on"
        )
    start = date.fromisoformat(query.startdt)
    end = date.fromisoformat(query.enddt)
    seen: set[str] = set()
    hits: list[EftsHit] = []
    aggregations: tuple[EftsAggregation, ...] = ()
    total_value = 0
    any_gte = False
    for slice_start, slice_end in _month_slices(start, end):
        sliced = replace(
            query,
            startdt=slice_start.isoformat(),
            enddt=slice_end.isoformat(),
        )
        for page in iter_search_pages(sliced, client=client):
            if not aggregations:
                aggregations = page.aggregations
            if page.offset == 0:
                total_value += page.total_value
            any_gte = any_gte or page.total_relation == "gte"
            for hit in page.hits:
                if hit.document_id not in seen:
                    seen.add(hit.document_id)
                    hits.append(hit)
    return EftsSearchResult(
        hits=tuple(hits),
        coverage=EftsCoverage(
            total_value=total_value,
            total_relation="gte" if any_gte else "eq",
            hits_returned=len(hits),
            truncated=any_gte,
            ceiling_reached=False,
            items_cache_hazard=bool(query.items),
        ),
        aggregations=aggregations,
    )
