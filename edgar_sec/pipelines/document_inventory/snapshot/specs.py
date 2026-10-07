"""Declarative relational specifications for document inventory snapshot tables."""

from __future__ import annotations

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.infra.storage.dag.spec import RelationSpec

from .schema import (
    SNAPSHOT_ACCESSIONS_SCHEMA,
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
)

INVENTORY_ACCESSIONS_SPEC = RelationSpec(
    name="accessions",
    schema=SNAPSHOT_ACCESSIONS_SCHEMA,
    primary_key=("accession",),
    merge_strategy="upsert",
    sort_order=("form", "filing_date", "accession"),
    entity_key="accession",
)

INVENTORY_ENTRIES_SPEC = RelationSpec(
    name="entries",
    schema=ENTRY_SCHEMA,
    primary_key=("entry_id",),
    merge_strategy="scoped_mask",
    parent_relation="accessions",
    parent_join_key=("accession",),
    sort_order=("accession", "sequence"),
    entity_key="accession",
)

INVENTORY_ACCESSION_SOURCES_SPEC = RelationSpec(
    name="accession_sources",
    schema=SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    primary_key=("accession", "source_cik"),
    merge_strategy="upsert",
    sort_order=("source_cik", "accession"),
    entity_key="source_cik",
)

INVENTORY_RELATIONS = (
    INVENTORY_ACCESSIONS_SPEC,
    INVENTORY_ENTRIES_SPEC,
    INVENTORY_ACCESSION_SOURCES_SPEC,
)

__all__ = [
    "INVENTORY_ACCESSIONS_SPEC",
    "INVENTORY_ACCESSION_SOURCES_SPEC",
    "INVENTORY_ENTRIES_SPEC",
    "INVENTORY_RELATIONS",
]
