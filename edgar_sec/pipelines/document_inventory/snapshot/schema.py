"""Arrow schemas for published inventory snapshot relations."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA

SNAPSHOT_RELATION_VERSION = "1"
LOOKUP_LAYOUT_VERSION = "1"

#: One row per canonical accession in the snapshot. Sorted on write by
#: (form, filing_date, accession) so row-group min/max statistics prune
#: filing-form and filing-date predicates.
SNAPSHOT_ACCESSIONS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("filing_cik", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("bundle_url", pa.string()),
        ("bundle_size", pa.int64()),
        ("index_url", pa.string()),
        ("index_sha256", pa.string()),
        ("first_indexed_by", pa.string()),
    ]
)

#: One row per unique (accession, source_cik) relationship from filing-cohort
#: plans. Sorted on write by (source_cik, accession).
SNAPSHOT_ACCESSION_SOURCES_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("source_cik", pa.string()),
        ("first_seen_by", pa.string()),
    ]
)

#: The key column used to index an accession relation.
KEY_COLUMN = "accession"
