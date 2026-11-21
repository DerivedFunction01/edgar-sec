from __future__ import annotations

import pyarrow as pa

from edgar_sec.domain.submissions.schemas import (
    ADDRESS_STRUCT,
    DATASET_NAME,
    FILING_STRUCT,
    FORMER_NAME_STRUCT,
    SCHEMA_VERSION,
    SUBMISSION_METADATA_SCHEMA,
    TERMINAL_STATUSES,
)


def test_submission_metadata_schema_invariants() -> None:
    assert DATASET_NAME == "submission_metadata"
    assert SCHEMA_VERSION == "1.0.0"
    assert isinstance(SUBMISSION_METADATA_SCHEMA, pa.Schema)

    field_names = SUBMISSION_METADATA_SCHEMA.names
    assert "cik" in field_names
    assert "status" in field_names
    assert "identity" in field_names
    assert "classification" in field_names
    assert "filings" in field_names
    assert "anomalies" in field_names

    cik_type = SUBMISSION_METADATA_SCHEMA.field("cik").type
    assert pa.types.is_string(cik_type)

    filings_type = SUBMISSION_METADATA_SCHEMA.field("filings").type
    assert pa.types.is_list(filings_type)
    assert filings_type.value_type == FILING_STRUCT

    address_fields = {f.name for f in ADDRESS_STRUCT}
    assert "city" in address_fields
    assert "state_or_country" in address_fields
    assert "zip_code" in address_fields

    former_fields = {f.name for f in FORMER_NAME_STRUCT}
    assert "name" in former_fields
    assert "from_date" in former_fields
    assert "to_date" in former_fields

    assert "ok" in TERMINAL_STATUSES
    assert "partial" in TERMINAL_STATUSES
    assert "failed" in TERMINAL_STATUSES
