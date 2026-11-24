"""Cohort relation schemas, fingerprinting, and staged-output reads."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.duckdb import arrow_reader
from edgar_sec.pipelines.document_inventory.run_state.run_manifest import (
    ManifestMismatchError,
)

__all__ = [
    "COHORT_ACCESSIONS_SCHEMA",
    "COHORT_SOURCES_SCHEMA",
    "hash_relations",
    "validate_output_schema",
    "work_items",
]

COHORT_ACCESSIONS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("filing_cik", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("index_url", pa.string()),
    ]
)
COHORT_SOURCES_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("source_cik", pa.string()),
        ("first_seen_by", pa.string()),
    ]
)


def hash_relations(accessions_path: Path, sources_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"document-inventory-cohort-v1\0")
    for label, path in (("accessions", accessions_path), ("sources", sources_path)):
        digest.update(label.encode("ascii") + b"\0")
        for batch_index, batch in enumerate(
            pq.ParquetFile(path).iter_batches(
                batch_size=resolve_parquet_read_batch_size()
            ),
            start=1,
        ):
            rows = batch.to_pylist()
            for row in rows:
                encoded = canonical_json(row).encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
            del rows
            if batch_index % 16 == 0:
                reclaim()
    return digest.hexdigest()


def validate_output_schema(path: Path, schema: pa.Schema) -> None:
    actual = pq.ParquetFile(path).schema_arrow
    if actual.names != schema.names or any(
        actual.field(name).type != field.type
        for name, field in zip(schema.names, schema, strict=True)
    ):
        raise ManifestMismatchError(f"projection output schema mismatch: {path.name}")


def work_items(connection: Any):
    reader = arrow_reader(
        connection,
        "SELECT accession, index_url, vehicle, archive_cik, primary_document, is_inline_xbrl, form FROM work_candidates ORDER BY accession",
    )
    for batch_index, batch in enumerate(reader, start=1):
        yield from (
            IndexWorkItem(
                AccessionNumber(row["accession"]),
                row["index_url"],
                vehicle=row["vehicle"],
                archive_cik=row["archive_cik"],
                primary_document=row["primary_document"],
                is_inline_xbrl=bool(row["is_inline_xbrl"]),
                form=row["form"],
            )
            for row in batch.to_pylist()
        )
        if batch_index % 16 == 0:
            reclaim()
