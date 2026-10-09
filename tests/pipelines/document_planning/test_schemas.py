import pyarrow as pa

from edgar_sec.pipelines.document_planning.schemas import (
    MATCHER_VERSION,
    PROFILE_SCHEMA_VERSION,
    TARGET_COLUMNS,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)


def test_target_schema_matches_order_types_and_nullability() -> None:
    assert TARGET_SCHEMA.names == list(TARGET_COLUMNS)
    assert [field.type for field in TARGET_SCHEMA] == [
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.bool_(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.string(),
        pa.int32(),
        pa.int64(),
        pa.string(),
    ]
    assert {field.name for field in TARGET_SCHEMA if field.nullable} == {
        "inventory_entry_id",
        "status_reason",
        "target_url",
        "sequence",
        "byte_size",
    }


def test_planning_versions_are_stable_contract_values() -> None:
    assert TARGET_SCHEMA_VERSION == 1
    assert PROFILE_SCHEMA_VERSION == "1"
    assert MATCHER_VERSION == "target-matcher-v1"
