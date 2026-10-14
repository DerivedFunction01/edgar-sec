"""Parquet serialization and deserialization for discovered linkbases."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.discovery import DiscoveredLinkbase
from edgar_sec.infra.storage.parquet import write_parquet_table

LINKBASE_INVENTORY_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("cik", pa.int64(), nullable=False),
        pa.field("linkbase_type", pa.string(), nullable=False),
        pa.field("document_type", pa.string(), nullable=False),
        pa.field("filename", pa.string(), nullable=False),
        pa.field("archive_url", pa.string(), nullable=False),
        pa.field("byte_size", pa.int64(), nullable=True),
        pa.field("sequence", pa.int32(), nullable=True),
        pa.field("description", pa.string(), nullable=True),
    ]
)


def linkbases_to_arrow_table(
    linkbases: Sequence[DiscoveredLinkbase],
) -> pa.Table:
    """Convert discovered linkbase records to a typed PyArrow table."""
    arrays = [
        pa.array([str(lb.accession) for lb in linkbases], type=pa.string()),
        pa.array([int(lb.cik) for lb in linkbases], type=pa.int64()),
        pa.array([lb.linkbase_type.value for lb in linkbases], type=pa.string()),
        pa.array([lb.document_type for lb in linkbases], type=pa.string()),
        pa.array([lb.filename for lb in linkbases], type=pa.string()),
        pa.array([lb.archive_url for lb in linkbases], type=pa.string()),
        pa.array([lb.byte_size for lb in linkbases], type=pa.int64()),
        pa.array([lb.sequence for lb in linkbases], type=pa.int32()),
        pa.array([lb.description for lb in linkbases], type=pa.string()),
    ]
    return pa.Table.from_arrays(arrays, schema=LINKBASE_INVENTORY_SCHEMA)


def write_linkbase_parquet(
    linkbases: Sequence[DiscoveredLinkbase],
    destination: Path | str,
) -> int:
    """Write discovered linkbases into an atomic, compressed Parquet file."""
    table = linkbases_to_arrow_table(linkbases)
    return write_parquet_table(table, destination)


def read_linkbase_parquet(source: Path | str) -> pa.Table:
    """Read linkbase inventory Parquet file into an Arrow Table."""
    return pq.read_table(os.fspath(source))
