from __future__ import annotations

import pyarrow as pa

from edgar_sec.pipelines.document_acquisition.arrow_schemas import WORK_ORDER_SCHEMA
from edgar_sec.pipelines.document_acquisition.schemas import target_relation_schema


def test_work_order_schema_is_ordered_extension_of_s6_target_schema() -> None:
    target_schema = target_relation_schema()
    expected_schema = pa.schema(
        [
            *target_schema,
            pa.field("executable", pa.bool_(), nullable=False),
            pa.field("skip_reason", pa.string(), nullable=True),
        ],
        metadata=target_schema.metadata,
    )

    assert WORK_ORDER_SCHEMA.equals(expected_schema, check_metadata=True)
    assert WORK_ORDER_SCHEMA.names == [
        *target_schema.names,
        "executable",
        "skip_reason",
    ]
