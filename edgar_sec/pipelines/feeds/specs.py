"""Declarative relational specification for the feed-events ledger."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.infra.storage.dag.spec import RelationSpec

FEED_EVENTS_SCHEMA_VERSION = "1"

FEED_EVENTS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("accession_normalized", pa.string()),
        ("source", pa.string()),
        ("cik", pa.string()),
        ("form", pa.string()),
        ("company_name", pa.string()),
        ("filing_date", pa.date32()),
        ("acceptance_datetime", pa.string()),
        ("link", pa.string()),
        ("snapshot_id", pa.string()),
        ("fetched_at", pa.string()),
    ]
)

FEED_EVENTS_SPEC = RelationSpec(
    name="feed_events",
    schema=FEED_EVENTS_SCHEMA,
    primary_key=("accession_normalized", "source"),
    merge_strategy="append",
    sort_order=("accession_normalized", "source"),
    entity_key="accession_normalized",
)

FEED_RELATION_SPECS = (FEED_EVENTS_SPEC,)

__all__ = [
    "FEED_EVENTS_SCHEMA",
    "FEED_EVENTS_SCHEMA_VERSION",
    "FEED_EVENTS_SPEC",
    "FEED_RELATION_SPECS",
]
