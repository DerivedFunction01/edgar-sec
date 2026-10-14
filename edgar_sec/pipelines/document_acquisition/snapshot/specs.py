"""Declarative relational specifications for acquisition snapshots."""

from __future__ import annotations

from edgar_sec.infra.storage.dag.spec import RelationSpec

from .schema import (
    ACCESSION_CIKS_SCHEMA,
    ACQUISITION_ATTEMPTS_SCHEMA,
    ACQUISITION_SLOTS_SCHEMA,
    BINARY_PAYLOADS_SCHEMA,
    LOGICAL_DOCUMENTS_SCHEMA,
    OPERATION_ATTEMPTS_SCHEMA,
    OPERATION_RESULTS_SCHEMA,
    PAYLOAD_INDEX_SCHEMA,
    REPRESENTATIONS_SCHEMA,
    REPRESENTATION_INPUTS_SCHEMA,
    SLOT_TYPES_SCHEMA,
    SOURCE_ASSETS_SCHEMA,
    SOURCE_PAYLOADS_SCHEMA,
    TARGET_RESULTS_SCHEMA,
    TARGET_SLOT_SELECTIONS_SCHEMA,
    TEXT_PAYLOADS_SCHEMA,
)

ACCESSION_CIKS_SPEC = RelationSpec(
    name="accession_ciks",
    schema=ACCESSION_CIKS_SCHEMA,
    primary_key=("accession",),
    merge_strategy="upsert",
    sort_order=("accession",),
    entity_key="accession",
)

SOURCE_ASSETS_SPEC = RelationSpec(
    name="source_assets",
    schema=SOURCE_ASSETS_SCHEMA,
    primary_key=("source_asset_id",),
    merge_strategy="upsert",
    sort_order=("accession", "source_asset_id"),
    entity_key="accession",
)

ACQUISITION_SLOTS_SPEC = RelationSpec(
    name="acquisition_slots",
    schema=ACQUISITION_SLOTS_SCHEMA,
    primary_key=("accession", "sequence", "observation_id"),
    merge_strategy="append",
    sort_order=("accession", "sequence", "observation_id"),
    entity_key="accession",
)

SLOT_TYPES_SPEC = RelationSpec(
    name="slot_types",
    schema=SLOT_TYPES_SCHEMA,
    primary_key=("type_evidence_id",),
    merge_strategy="append",
    sort_order=("accession", "sequence", "type_evidence_id"),
    entity_key="accession",
)

LOGICAL_DOCUMENTS_SPEC = RelationSpec(
    name="logical_documents",
    schema=LOGICAL_DOCUMENTS_SCHEMA,
    primary_key=("logical_document_id",),
    merge_strategy="upsert",
    sort_order=("accession", "logical_document_id"),
    entity_key="accession",
)

TARGET_RESULTS_SPEC = RelationSpec(
    name="target_results",
    schema=TARGET_RESULTS_SCHEMA,
    primary_key=("run_id", "target_id"),
    merge_strategy="append",
    sort_order=("accession", "target_id", "run_id"),
    entity_key="accession",
)

TARGET_SLOT_SELECTIONS_SPEC = RelationSpec(
    name="target_slot_selections",
    schema=TARGET_SLOT_SELECTIONS_SCHEMA,
    primary_key=("run_id", "target_id", "resolution_id"),
    merge_strategy="append",
    sort_order=("accession", "target_id", "resolution_id"),
    entity_key="accession",
)

ACQUISITION_ATTEMPTS_SPEC = RelationSpec(
    name="acquisition_attempts",
    schema=ACQUISITION_ATTEMPTS_SCHEMA,
    primary_key=("run_id", "attempt_id"),
    merge_strategy="append",
    sort_order=("target_id", "attempt_number", "attempt_id"),
    entity_key="target_id",
)

SOURCE_PAYLOADS_SPEC = RelationSpec(
    name="source_payloads",
    schema=SOURCE_PAYLOADS_SCHEMA,
    primary_key=("source_asset_id", "payload_sha256"),
    merge_strategy="upsert",
    sort_order=("source_asset_id", "payload_sha256"),
    entity_key="source_asset_id",
)

OPERATION_RESULTS_SPEC = RelationSpec(
    name="operation_results",
    schema=OPERATION_RESULTS_SCHEMA,
    primary_key=("run_id", "operation_id"),
    merge_strategy="append",
    sort_order=("target_id", "operation_id", "run_id"),
    entity_key="target_id",
)

OPERATION_ATTEMPTS_SPEC = RelationSpec(
    name="operation_attempts",
    schema=OPERATION_ATTEMPTS_SCHEMA,
    primary_key=("run_id", "operation_attempt_id"),
    merge_strategy="append",
    sort_order=("operation_id", "attempt_number", "operation_attempt_id"),
    entity_key="operation_id",
)

REPRESENTATIONS_SPEC = RelationSpec(
    name="representations",
    schema=REPRESENTATIONS_SCHEMA,
    primary_key=("representation_id",),
    merge_strategy="upsert",
    sort_order=("logical_document_id", "representation_id"),
    entity_key="logical_document_id",
)

REPRESENTATION_INPUTS_SPEC = RelationSpec(
    name="representation_inputs",
    schema=REPRESENTATION_INPUTS_SCHEMA,
    primary_key=("representation_id", "input_ordinal"),
    merge_strategy="upsert",
    sort_order=("representation_id", "input_ordinal"),
    entity_key="representation_id",
)

PAYLOAD_INDEX_SPEC = RelationSpec(
    name="payload_index",
    schema=PAYLOAD_INDEX_SCHEMA,
    primary_key=("payload_sha256",),
    merge_strategy="upsert",
    sort_order=("payload_sha256",),
    entity_key="payload_sha256",
)

BINARY_PAYLOADS_SPEC = RelationSpec(
    name="binary_payloads",
    schema=BINARY_PAYLOADS_SCHEMA,
    primary_key=("payload_sha256",),
    merge_strategy="upsert",
    sort_order=("payload_sha256",),
    entity_key="payload_sha256",
)

TEXT_PAYLOADS_SPEC = RelationSpec(
    name="text_payloads",
    schema=TEXT_PAYLOADS_SCHEMA,
    primary_key=("payload_sha256",),
    merge_strategy="upsert",
    sort_order=("payload_sha256",),
    entity_key="payload_sha256",
)

ACQUISITION_RELATIONS: tuple[RelationSpec, ...] = (
    ACCESSION_CIKS_SPEC,
    SOURCE_ASSETS_SPEC,
    ACQUISITION_SLOTS_SPEC,
    SLOT_TYPES_SPEC,
    LOGICAL_DOCUMENTS_SPEC,
    TARGET_RESULTS_SPEC,
    TARGET_SLOT_SELECTIONS_SPEC,
    ACQUISITION_ATTEMPTS_SPEC,
    SOURCE_PAYLOADS_SPEC,
    OPERATION_RESULTS_SPEC,
    OPERATION_ATTEMPTS_SPEC,
    REPRESENTATIONS_SPEC,
    REPRESENTATION_INPUTS_SPEC,
    PAYLOAD_INDEX_SPEC,
    BINARY_PAYLOADS_SPEC,
    TEXT_PAYLOADS_SPEC,
)

ACQUISITION_RELATIONS_BY_NAME: dict[str, RelationSpec] = {
    spec.name: spec for spec in ACQUISITION_RELATIONS
}

__all__ = [
    "ACCESSION_CIKS_SPEC",
    "ACQUISITION_ATTEMPTS_SPEC",
    "ACQUISITION_RELATIONS",
    "ACQUISITION_RELATIONS_BY_NAME",
    "ACQUISITION_SLOTS_SPEC",
    "BINARY_PAYLOADS_SPEC",
    "LOGICAL_DOCUMENTS_SPEC",
    "OPERATION_ATTEMPTS_SPEC",
    "OPERATION_RESULTS_SPEC",
    "PAYLOAD_INDEX_SPEC",
    "REPRESENTATIONS_SPEC",
    "REPRESENTATION_INPUTS_SPEC",
    "SLOT_TYPES_SPEC",
    "SOURCE_ASSETS_SPEC",
    "SOURCE_PAYLOADS_SPEC",
    "TARGET_RESULTS_SPEC",
    "TARGET_SLOT_SELECTIONS_SPEC",
    "TEXT_PAYLOADS_SPEC",
]
