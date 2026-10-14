from __future__ import annotations

from edgar_sec.pipelines.document_acquisition.snapshot.schema import (
    SNAPSHOT_RELATION_SCHEMAS,
)
from edgar_sec.pipelines.document_acquisition.snapshot.specs import (
    ACQUISITION_RELATIONS,
    ACQUISITION_RELATIONS_BY_NAME,
    BINARY_PAYLOADS_SPEC,
    PAYLOAD_INDEX_SPEC,
    TEXT_PAYLOADS_SPEC,
)


def test_acquisition_relation_specs_are_valid() -> None:
    assert len(ACQUISITION_RELATIONS) == 16
    assert len(ACQUISITION_RELATIONS_BY_NAME) == 16
    assert len(SNAPSHOT_RELATION_SCHEMAS) == 16

    for spec in ACQUISITION_RELATIONS:
        assert spec.name in ACQUISITION_RELATIONS_BY_NAME
        assert spec.schema == SNAPSHOT_RELATION_SCHEMAS[spec.name]
        assert spec.primary_key
        assert spec.entity_key
        assert spec.merge_strategy in ("upsert", "append")


def test_payload_specs_have_correct_keys_and_strategies() -> None:
    assert PAYLOAD_INDEX_SPEC.primary_key == ("payload_sha256",)
    assert PAYLOAD_INDEX_SPEC.merge_strategy == "upsert"

    assert TEXT_PAYLOADS_SPEC.primary_key == ("payload_sha256",)
    assert TEXT_PAYLOADS_SPEC.merge_strategy == "upsert"

    assert BINARY_PAYLOADS_SPEC.primary_key == ("payload_sha256",)
    assert BINARY_PAYLOADS_SPEC.merge_strategy == "upsert"
