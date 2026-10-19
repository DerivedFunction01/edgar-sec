import pyarrow as pa

from edgar_sec.pipelines.document_planning.schemas import (
    MATCHER_VERSION,
    PLAN_BUNDLE_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    TARGET_COLUMNS,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA,
    SOURCE_REQUEST_SCHEMA,
    OPERATION_INPUT_SCHEMA,
)


def test_target_schema_matches_order_types_and_nullability() -> None:
    assert TARGET_SCHEMA.names == list(TARGET_COLUMNS)
    assert [field.type for field in TARGET_SCHEMA] == [
        *(pa.string() for _ in range(8)),
        pa.bool_(),
        *(pa.string() for _ in range(6)),
        pa.int32(),
        pa.int64(),
        *(pa.string() for _ in range(2)),
    ]
    assert {field.name for field in TARGET_SCHEMA if field.nullable} == {
        "inventory_entry_id",
        "status_reason",
        "target_url",
        "sequence",
        "byte_size",
        "catalog_direct_selection",
        "report_date",
    }


def test_planning_versions_are_stable_contract_values() -> None:
    assert TARGET_SCHEMA_VERSION == 2
    assert PLAN_BUNDLE_SCHEMA_VERSION == 5
    assert PROFILE_SCHEMA_VERSION == "1"
    assert MATCHER_VERSION == "target-matcher-v5"
    assert TARGET_OPERATION_SCHEMA.names == [
        "operation_id",
        "target_id",
        "operation",
        "requested",
        "request_mode",
    ]
    assert SOURCE_REQUEST_SCHEMA.names == [
        "source_request_id",
        "target_id",
        "source_role",
        "source_origin",
        "retrieval_mode",
        "request_url",
        "sequence",
        "canonical_path",
    ]
    assert OPERATION_INPUT_SCHEMA.names == [
        "operation_id",
        "input_ordinal",
        "source_request_id",
        "input_role",
    ]
