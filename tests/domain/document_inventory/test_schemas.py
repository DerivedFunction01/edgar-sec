"""Tests for the durable inventory entry schema."""

import pyarrow as pa

from edgar_sec.domain.document_inventory.schemas import (
    ENTRY_SCHEMA,
    ENTRY_SCHEMA_VERSION,
)


def test_entry_schema_has_stable_column_order_and_types() -> None:
    assert ENTRY_SCHEMA.names == [
        "entry_id",
        "accession",
        "table_kind",
        "row_ordinal",
        "sequence",
        "document_type",
        "document_label",
        "description",
        "filename",
        "href",
        "archive_url",
        "byte_size",
    ]
    assert ENTRY_SCHEMA.field("row_ordinal").type == pa.int32()
    assert ENTRY_SCHEMA.field("byte_size").type == pa.int64()
    assert ENTRY_SCHEMA_VERSION == 1
