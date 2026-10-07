"""Tests for document inventory RelationSpecs."""

from edgar_sec.infra.storage.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.document_inventory.snapshot.specs import (
    INVENTORY_ACCESSION_SOURCES_SPEC,
    INVENTORY_ACCESSIONS_SPEC,
    INVENTORY_ENTRIES_SPEC,
    INVENTORY_RELATIONS,
)


def test_inventory_relation_specs_are_valid() -> None:
    assert len(INVENTORY_RELATIONS) == 3

    assert INVENTORY_ACCESSIONS_SPEC.name == "accessions"
    assert INVENTORY_ACCESSIONS_SPEC.primary_key == ("accession",)
    assert INVENTORY_ACCESSIONS_SPEC.entity_key == "accession"
    assert INVENTORY_ACCESSIONS_SPEC.merge_strategy == "upsert"
    assert INVENTORY_ACCESSIONS_SPEC.max_rows_per_part == DEFAULT_ROW_GROUP_SIZE

    assert INVENTORY_ENTRIES_SPEC.name == "entries"
    assert INVENTORY_ENTRIES_SPEC.primary_key == ("entry_id",)
    assert INVENTORY_ENTRIES_SPEC.entity_key == "accession"
    assert INVENTORY_ENTRIES_SPEC.merge_strategy == "scoped_mask"
    assert INVENTORY_ENTRIES_SPEC.parent_relation == "accessions"
    assert INVENTORY_ENTRIES_SPEC.parent_join_key == ("accession",)
    assert INVENTORY_ENTRIES_SPEC.max_rows_per_part == DEFAULT_ROW_GROUP_SIZE

    assert INVENTORY_ACCESSION_SOURCES_SPEC.name == "accession_sources"
    assert INVENTORY_ACCESSION_SOURCES_SPEC.primary_key == (
        "accession",
        "source_cik",
    )
    assert INVENTORY_ACCESSION_SOURCES_SPEC.entity_key == "source_cik"
    assert INVENTORY_ACCESSION_SOURCES_SPEC.merge_strategy == "upsert"
    assert INVENTORY_ACCESSION_SOURCES_SPEC.max_rows_per_part == DEFAULT_ROW_GROUP_SIZE
