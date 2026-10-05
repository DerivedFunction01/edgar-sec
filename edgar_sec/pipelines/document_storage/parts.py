"""Byte-budgeted part planning and IO for document snapshots.

Parts are budgeted by document bytes, not row count: normalized text sizes vary by
orders of magnitude, so row-counted parts would too. Part paths are snapshot-relative,
so a manifest cannot name another snapshot's part.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.infra.storage.atomic import _fsync_dir
from edgar_sec.infra.storage.manifests import (
    PART_KIND_INDEX,
    PART_KIND_PAYLOAD,
    SnapshotPart,
)
from edgar_sec.infra.storage.parquet import (
    DEFAULT_COMPRESSION,
    DEFAULT_ROW_GROUP_SIZE,
)

#: Part columns. The index and payload kinds are projections of one logical
#: record, split so a consumer can read metadata without the text.
INDEX_COLUMNS: tuple[str, ...] = (
    "occurrence_id",
    "source_cik",
    "accession",
    "form",
    "filing_date",
    "report_date",
    "document_path",
    "doc_id",
    "mime_type",
    "byte_size",
    "payload_file",
)
# ``filing_year``/``filing_quarter`` are derived at consolidation time, so a
# snapshot from an older code version consolidates alongside a newer one.
PAYLOAD_COLUMNS: tuple[str, ...] = ("doc_id", "clean_text")

INDEX_SCHEMA = pa.schema([(name, pa.string()) for name in INDEX_COLUMNS])
PAYLOAD_SCHEMA = pa.schema([("doc_id", pa.string()), ("clean_text", pa.string())])


class PartError(RuntimeError):
    """A snapshot part could not be planned, written, or read."""


@dataclass(frozen=True, slots=True)
class PlannedPart:
    """One part the planner intends to write."""

    path: str
    kind: str
    doc_ids: tuple[str, ...]
    estimated_bytes: int


def quarter_path(year: int, quarter: str, kind: str) -> str:
    """Return a part's path relative to its own snapshot directory.

    Snapshot-relative: a part is meaningless apart from the snapshot that owns it.
    """
    return f"parts/{kind}/{year}-{quarter}.parquet"


def plan_parts(
    doc_sizes: Sequence[tuple[str, int]],
    *,
    year: int,
    quarter: str,
    target_bytes: int,
    kind: str,
) -> list[PlannedPart]:
    """Split a quarter's documents into byte-budgeted parts.

    ``doc_ids`` must be sorted: each part covers a contiguous range a reader streams.
    """
    if target_bytes <= 0:
        raise PartError("target_bytes must be positive")
    if not doc_sizes:
        return []

    parts: list[PlannedPart] = []
    current_ids: list[str] = []
    current_bytes = 0
    for doc_id, size in doc_sizes:
        would_exceed = current_ids and current_bytes + size > target_bytes
        if would_exceed:
            parts.append(_planned(current_ids, current_bytes, year, quarter, kind))
            current_ids = []
            current_bytes = 0
        current_ids.append(doc_id)
        current_bytes += max(0, int(size))
    if current_ids:
        parts.append(_planned(current_ids, current_bytes, year, quarter, kind))
    return parts


def _planned(
    doc_ids: list[str], total_bytes: int, year: int, quarter: str, kind: str
) -> PlannedPart:
    return PlannedPart(
        path=quarter_path(year, quarter, kind),
        kind=kind,
        doc_ids=tuple(doc_ids),
        estimated_bytes=total_bytes,
    )


def write_index_part(
    snapshot_dir: Path, part: PlannedPart, rows: Sequence[Mapping[str, Any]]
) -> SnapshotPart:
    """Write one index part and return its manifest entry."""
    table = pa.Table.from_pydict(
        {name: [row.get(name) for row in rows] for name in INDEX_COLUMNS},
        schema=INDEX_SCHEMA,
    )
    return _write_part(snapshot_dir, part, table)


def write_payload_part(
    snapshot_dir: Path, part: PlannedPart, rows: Sequence[tuple[str, str]]
) -> SnapshotPart:
    """Write one payload part and return its manifest entry."""
    table = pa.Table.from_pydict(
        {
            "doc_id": [doc_id for doc_id, _text in rows],
            "clean_text": [text for _doc_id, text in rows],
        },
        schema=PAYLOAD_SCHEMA,
    )
    return _write_part(snapshot_dir, part, table)


def _write_part(root: Path, part: PlannedPart, table: pa.Table) -> SnapshotPart:
    dest = Path(root) / part.path
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.tmp.{os.getpid()}")
    try:
        pq.write_table(
            table,
            tmp,
            compression=DEFAULT_COMPRESSION,
            row_group_size=DEFAULT_ROW_GROUP_SIZE,
        )
        os.replace(tmp, dest)
        _fsync_dir(str(dest.parent))
    finally:
        tmp.unlink(missing_ok=True)
    return SnapshotPart(
        path=part.path,
        kind=part.kind,
        doc_ids=part.doc_ids,
        row_count=table.num_rows,
        byte_size=dest.stat().st_size,
    )


def read_part(snapshot_dir: Path, part: SnapshotPart) -> pa.Table:
    """Read one part's rows."""
    path = Path(snapshot_dir) / part.path
    if not path.is_file():
        raise PartError(f"snapshot part not found: {path}")
    return pq.read_table(path)


def relation_for_parts(parts: Iterable[SnapshotPart], base_dir: Path) -> str:
    """Return a DuckDB relation over parts resolved against ``base_dir``.

    Quotes each path; ``validate_part_paths`` rejects quote-bearing paths first.
    Wrapped in a subquery: DuckDB rejects a bare call inside a parenthesized FROM.
    """
    files = [str((Path(base_dir) / part.path).resolve()) for part in parts]
    if not files:
        raise PartError("cannot build a relation over zero parts")
    listed = ", ".join("'" + path.replace("'", "''") + "'" for path in files)
    return f"(SELECT * FROM read_parquet([{listed}]))"


def validate_part_paths(parts: Iterable[SnapshotPart], base_dir: Path) -> None:
    """Reject part paths that are missing or contain unsafe characters.

    A recorded path is interpolated into SQL, and a manifest is an editable file.
    """
    for part in parts:
        if not part.path:
            raise PartError("part path is empty")
        if ".." in Path(part.path).parts or Path(part.path).is_absolute():
            raise PartError(f"part path escapes the snapshots root: {part.path}")
        if "'" in part.path or '"' in part.path or ";" in part.path:
            raise PartError(f"part path contains an unsafe character: {part.path}")
        if not (Path(base_dir) / part.path).is_file():
            raise PartError(f"part file is missing: {part.path}")


def payload_doc_ids(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return the document ids a payload part covers, in order."""
    return tuple(str(row["doc_id"]) for row in rows)


__all__ = [
    "INDEX_COLUMNS",
    "INDEX_SCHEMA",
    "PART_KIND_INDEX",
    "PART_KIND_PAYLOAD",
    "PAYLOAD_COLUMNS",
    "PAYLOAD_SCHEMA",
    "PartError",
    "PlannedPart",
    "payload_doc_ids",
    "plan_parts",
    "quarter_path",
    "read_part",
    "relation_for_parts",
    "validate_part_paths",
    "write_index_part",
    "write_payload_part",
]
