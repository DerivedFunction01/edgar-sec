"""Declarative relational specifications for metadata sync snapshots."""

from __future__ import annotations

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.infra.storage.dag.spec import RelationSpec

from .roster import SNAPSHOT_CIK_INDEX_SCHEMA

METADATA_SUBMISSIONS_SPEC = RelationSpec(
    name="submissions",
    schema=SUBMISSION_METADATA_SCHEMA,
    primary_key=("cik",),
    merge_strategy="upsert",
    sort_order=("cik",),
    entity_key="cik",
)

METADATA_CIK_INDEX_SPEC = RelationSpec(
    name="ciks",
    schema=SNAPSHOT_CIK_INDEX_SCHEMA,
    primary_key=("cik",),
    merge_strategy="upsert",
    sort_order=("cik",),
    entity_key="cik",
)

METADATA_RELATION_SPECS = (METADATA_SUBMISSIONS_SPEC, METADATA_CIK_INDEX_SPEC)

__all__ = [
    "METADATA_CIK_INDEX_SPEC",
    "METADATA_RELATION_SPECS",
    "METADATA_SUBMISSIONS_SPEC",
]
