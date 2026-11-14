"""Multi-form fan-out for the EFTS client: per-form walks, unioned.

The endpoint collapses a comma-joined ``forms`` parameter to one
form, so each form is walked on its own and the hits union here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

from edgar_sec.apps.client.efts import (
    PAGE_SIZE,
    EftsAggregation,
    EftsBucket,
    EftsHit,
    EftsPage,
    EftsQuery,
)

__all__ = ["iter_pages_multi_form", "merge_aggregations"]

PageWalk = Callable[..., Iterator[EftsPage]]


def merge_aggregations(
    per_form: list[tuple[EftsAggregation, ...]],
) -> tuple[EftsAggregation, ...]:
    """Sum per-form aggregations bucket-wise into one aggregation set."""
    buckets: dict[str, dict[str, int]] = {}
    others: dict[str, int] = {}
    for aggregations in per_form:
        for agg in aggregations:
            counts = buckets.setdefault(agg.name, {})
            for bucket in agg.buckets:
                counts[bucket.key] = counts.get(bucket.key, 0) + bucket.doc_count
            others[agg.name] = others.get(agg.name, 0) + agg.sum_other_doc_count
    return tuple(
        EftsAggregation(
            name=name,
            buckets=tuple(
                EftsBucket(key=key, doc_count=count) for key, count in counts.items()
            ),
            sum_other_doc_count=others[name],
        )
        for name, counts in buckets.items()
    )


def iter_pages_multi_form(
    query: EftsQuery,
    *,
    client: Any,
    max_hits: int | None = None,
    walk: PageWalk,
) -> Iterator[EftsPage]:
    """Yield the union of the per-form walks as re-paginated pages.

    Each form is walked with the single-form page/window discipline;
    hits union by ``document_id`` in the order forms were given.
    """
    if max_hits is not None and max_hits < 0:
        raise ValueError("max_hits must be non-negative")
    if max_hits == 0:
        return
    seen: set[str] = set()
    hits: list[EftsHit] = []
    total_value = 0
    cross_form_dupes = 0
    any_gte = False
    per_form_aggs: list[tuple[EftsAggregation, ...]] = []
    for form in dict.fromkeys(query.forms):
        single = replace(query, forms=(form,))
        prior = set(seen)
        form_dupes: set[str] = set()
        for page in walk(single, client=client, max_hits=max_hits):
            if page.offset == 0:
                total_value += page.total_value
                any_gte = any_gte or page.total_relation == "gte"
                per_form_aggs.append(page.aggregations)
            for hit in page.hits:
                if hit.document_id in prior:
                    form_dupes.add(hit.document_id)
                if hit.document_id not in seen:
                    seen.add(hit.document_id)
                    hits.append(hit)
        cross_form_dupes += len(form_dupes)
    union_total = total_value - cross_form_dupes
    total_relation = "gte" if any_gte else "eq"
    aggregations = merge_aggregations(per_form_aggs)
    if max_hits is not None:
        hits = hits[:max_hits]
    chunks = [hits[i : i + PAGE_SIZE] for i in range(0, len(hits), PAGE_SIZE)]
    for start, chunk in enumerate(chunks or [[]]):
        yield EftsPage(
            hits=tuple(chunk),
            offset=start * PAGE_SIZE,
            total_value=union_total,
            total_relation=total_relation,
            aggregations=aggregations,
        )
