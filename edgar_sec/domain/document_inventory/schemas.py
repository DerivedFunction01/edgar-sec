"""The durable entry Arrow schema for the inventory dataset.

S4 writes this schema into every attempt's `entries.parquet`; S5 consumes it when
merging into the published snapshot. Field order and types are part of the
contract: bump `ENTRY_SCHEMA_VERSION` rather than editing the schema in place.
"""

from __future__ import annotations

import pyarrow as pa

#: Version persisted in run manifests and attempt manifests. Bump on schema change.
ENTRY_SCHEMA_VERSION = 1

ENTRY_SCHEMA = pa.schema(
    [
        ("entry_id", pa.string()),
        ("accession", pa.string()),
        ("table_kind", pa.string()),
        ("row_ordinal", pa.int32()),
        ("sequence", pa.int32()),
        ("document_type", pa.string()),
        ("document_label", pa.string()),
        ("description", pa.string()),
        ("filename", pa.string()),
        ("href", pa.string()),
        ("archive_url", pa.string()),
        ("byte_size", pa.int64()),
    ]
)
