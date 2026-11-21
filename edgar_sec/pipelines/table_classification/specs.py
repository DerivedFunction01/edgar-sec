"""Declarative relational specification for the classification store.

Carried relations republish the plan and merger schemas verbatim;
``run_provenance`` is the store's own header, one snapshot per run.
"""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.infra.storage.dag.spec import RelationSpec

from .schemas import OUTPUT_RELATION_SCHEMAS, PLAN_RELATION_SCHEMAS

STORE_SCHEMA_VERSION = "1"

RUN_PROVENANCE_SCHEMA = pa.schema(
    [
        ("store_snapshot_id", pa.string()),
        ("plan_id", pa.string()),
        ("plan_format_version", pa.string()),
        ("run_output_version", pa.string()),
        ("source_snapshot_id", pa.string()),
        ("registry_state", pa.string()),
        ("normalize_version", pa.string()),
        ("renderer_version", pa.string()),
        ("merged_at", pa.string()),
        ("published_at", pa.string()),
        ("filing_count", pa.int64()),
        ("profile_count", pa.int64()),
        ("target_count", pa.int64()),
        ("work_item_count", pa.int64()),
        ("document_count", pa.int64()),
        ("geometry_count", pa.int64()),
        ("classified_count", pa.int64()),
    ]
)

RUN_PROVENANCE_SPEC = RelationSpec(
    name="run_provenance",
    schema=RUN_PROVENANCE_SCHEMA,
    primary_key=("store_snapshot_id",),
    merge_strategy="append",
    sort_order=("store_snapshot_id",),
    entity_key="store_snapshot_id",
)

_PRIMARY_KEYS = {
    "provenance": ("plan_id",),
    "filings": ("accession",),
    "profile_application": ("accession", "family"),
    "document_targets": (
        "accession",
        "target_role",
        "target_type",
        "document_name",
    ),
    "work_items": ("work_item_id",),
    "filing_records": ("accession",),
    "geometry_inventory": ("accession", "source_document", "table_index"),
    "classifications": ("accession", "source_document", "table_index"),
}

_ENTITY_KEYS = {
    "provenance": "plan_id",
    "filings": "accession",
    "profile_application": "accession",
    "document_targets": "accession",
    "work_items": "accession",
    "filing_records": "accession",
    "geometry_inventory": "accession",
    "classifications": "accession",
}


def _carried_spec(name: str, schema: pa.Schema) -> RelationSpec:
    """Wrap one contract schema as a store relation specification."""
    return RelationSpec(
        name=name,
        schema=schema,
        primary_key=_PRIMARY_KEYS[name],
        merge_strategy="append",
        sort_order=_PRIMARY_KEYS[name],
        entity_key=_ENTITY_KEYS[name],
    )


CARRIED_RELATION_SPECS = tuple(
    _carried_spec(name, schema)
    for name, schema in (
        *PLAN_RELATION_SCHEMAS.items(),
        *OUTPUT_RELATION_SCHEMAS.items(),
    )
)

EVIDENCE_SCHEMA = pa.schema(
    [
        ("plan_id", pa.string()),
        ("accession", pa.string()),
        ("source_document", pa.string()),
        ("table_index", pa.int64()),
        ("ordinal", pa.int64()),
        ("group", pa.string()),
        ("detail", pa.string()),
        ("points", pa.float64()),
    ]
)

EVIDENCE_SPEC = RelationSpec(
    name="evidence",
    schema=EVIDENCE_SCHEMA,
    primary_key=("accession", "source_document", "table_index", "ordinal"),
    merge_strategy="append",
    sort_order=("accession", "source_document", "table_index", "ordinal"),
    entity_key="accession",
)

ASSEMBLED_TABLES_SCHEMA = pa.schema(
    [
        ("plan_id", pa.string()),
        ("accession", pa.string()),
        ("source_document", pa.string()),
        ("table_index", pa.int64()),
        ("family", pa.string()),
        ("flavor", pa.string()),
        ("assembled_family", pa.string()),
        ("mechanism", pa.string()),
    ]
)

ASSEMBLED_TABLES_SPEC = RelationSpec(
    name="assembled_tables",
    schema=ASSEMBLED_TABLES_SCHEMA,
    primary_key=("accession", "source_document", "table_index"),
    merge_strategy="append",
    sort_order=("accession", "source_document", "table_index"),
    entity_key="accession",
)

DERIVED_RELATION_SPECS = (EVIDENCE_SPEC, ASSEMBLED_TABLES_SPEC)

STORE_RELATION_SPECS = (
    RUN_PROVENANCE_SPEC,
    *CARRIED_RELATION_SPECS,
    *DERIVED_RELATION_SPECS,
)

STORE_SCHEMA_VERSIONS = {
    spec.name: STORE_SCHEMA_VERSION for spec in STORE_RELATION_SPECS
}

__all__ = [
    "ASSEMBLED_TABLES_SCHEMA",
    "ASSEMBLED_TABLES_SPEC",
    "CARRIED_RELATION_SPECS",
    "DERIVED_RELATION_SPECS",
    "EVIDENCE_SCHEMA",
    "EVIDENCE_SPEC",
    "RUN_PROVENANCE_SCHEMA",
    "RUN_PROVENANCE_SPEC",
    "STORE_RELATION_SPECS",
    "STORE_SCHEMA_VERSION",
    "STORE_SCHEMA_VERSIONS",
]
