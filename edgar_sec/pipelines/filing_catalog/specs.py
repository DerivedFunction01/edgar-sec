"""Declarative relational specifications for filing catalog snapshots."""

from __future__ import annotations

from edgar_sec.domain.filing_catalog.schemas import PROFILE_SCHEMA, TARGET_SCHEMA
from edgar_sec.infra.storage.dag.spec import RelationSpec

FILING_TARGETS_SPEC = RelationSpec(
    name="filing_targets",
    schema=TARGET_SCHEMA,
    primary_key=("occurrence_id",),
    merge_strategy="append",
    sort_order=("source_cik", "filing_date", "accession", "primary_document"),
    entity_key="occurrence_id",
)

COMPANY_PROFILES_SPEC = RelationSpec(
    name="company_profiles",
    schema=PROFILE_SCHEMA,
    primary_key=("cik",),
    merge_strategy="upsert",
    sort_order=("cik",),
    entity_key="cik",
)

CATALOG_RELATION_SPECS = (FILING_TARGETS_SPEC, COMPANY_PROFILES_SPEC)

__all__ = [
    "CATALOG_RELATION_SPECS",
    "COMPANY_PROFILES_SPEC",
    "FILING_TARGETS_SPEC",
]
