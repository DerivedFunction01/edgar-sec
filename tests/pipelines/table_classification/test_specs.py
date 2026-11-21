"""Specs: relation set and keys match the core lane's contract v1."""

from __future__ import annotations

from edgar_sec.pipelines.table_classification.schemas import (
    OUTPUT_RELATION_SCHEMAS,
    PLAN_RELATION_SCHEMAS,
)
from edgar_sec.pipelines.table_classification.specs import (
    STORE_RELATION_SPECS,
    STORE_SCHEMA_VERSIONS,
)

EXPECTED_RELATIONS = {
    "run_provenance",
    "provenance",
    "filings",
    "profile_application",
    "document_targets",
    "work_items",
    "filing_records",
    "geometry_inventory",
    "classifications",
    "evidence",
    "assembled_tables",
}

DERIVED_RELATIONS = {"evidence", "assembled_tables"}


def test_relation_set_matches_the_contract() -> None:
    assert {spec.name for spec in STORE_RELATION_SPECS} == EXPECTED_RELATIONS
    assert set(STORE_SCHEMA_VERSIONS) == EXPECTED_RELATIONS
    carried = set(PLAN_RELATION_SCHEMAS) | set(OUTPUT_RELATION_SCHEMAS)
    assert carried == EXPECTED_RELATIONS - {"run_provenance"} - DERIVED_RELATIONS


def test_derived_relation_shapes() -> None:
    specs = {spec.name: spec for spec in STORE_RELATION_SPECS}
    evidence = specs["evidence"]
    assert evidence.primary_key == (
        "accession",
        "source_document",
        "table_index",
        "ordinal",
    )
    assert evidence.schema.names == [
        "plan_id",
        "accession",
        "source_document",
        "table_index",
        "ordinal",
        "group",
        "detail",
        "points",
    ]
    assembled = specs["assembled_tables"]
    assert assembled.primary_key == ("accession", "source_document", "table_index")
    assert "assembled_family" in assembled.schema.names
    assert "mechanism" in assembled.schema.names


def test_carried_schemas_are_the_contract_schemas() -> None:
    contract = {**PLAN_RELATION_SCHEMAS, **OUTPUT_RELATION_SCHEMAS}
    for spec in STORE_RELATION_SPECS:
        if spec.name == "run_provenance" or spec.name in DERIVED_RELATIONS:
            continue
        assert spec.schema.equals(contract[spec.name])


def test_keys_match_the_contract() -> None:
    keys = {spec.name: spec.primary_key for spec in STORE_RELATION_SPECS}
    assert keys["run_provenance"] == ("store_snapshot_id",)
    assert keys["provenance"] == ("plan_id",)
    assert keys["filings"] == ("accession",)
    assert keys["profile_application"] == ("accession", "family")
    assert keys["work_items"] == ("work_item_id",)
    assert keys["filing_records"] == ("accession",)
    for name in ("geometry_inventory", "classifications"):
        assert keys[name] == ("accession", "source_document", "table_index")


def test_run_provenance_carries_the_seam_provenance() -> None:
    spec = next(s for s in STORE_RELATION_SPECS if s.name == "run_provenance")
    for column in (
        "plan_id",
        "plan_format_version",
        "run_output_version",
        "source_snapshot_id",
        "registry_state",
        "normalize_version",
        "renderer_version",
        "merged_at",
        "published_at",
    ):
        assert column in spec.schema.names
