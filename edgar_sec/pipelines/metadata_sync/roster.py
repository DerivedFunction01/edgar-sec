"""Content-addressed CIK roster datasets.

A roster is the single canonical statement of *which* CIKs a unit of work covers.
The list lives once, in an immutable Parquet dataset with a stable ordinal, and
everything else references it by identity.

Identity is content-derived from the ordered normalized CIK list together with
its display names and the roster schema version, so reformatting an input file
produces the same roster while reordering its rows does not. That is the point:
a roster says what the cohort *is*, not which bytes a curator happened to type.

A roster is a *handle* over that dataset rather than a pair of tuples. The CIK
cohort is the largest thing this pipeline carries, and holding it as Python
strings cost roughly six times what the file it came from costs to read. Callers
ask for the slice they need -- one chunk's ordinal range, the whole file rendered
as CSV -- and the handle reads exactly that from the dataset.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.parquet import read_parquet_schema, write_parquet_table

ROSTER_SCHEMA_VERSION = "1.0.0"
ROSTER_FILE_NAME = "ciks.parquet"
SNAPSHOT_CIK_INDEX_NAME = "ciks.parquet"
ROSTER_MANIFEST_KIND = "cik_roster"

_ID_PREFIX = "cik-roster-v1"

#: Rows pulled from the dataset per read. Bounds the transient list built while
#: streaming the identity hash or a CSV export, so neither grows with the cohort.
STREAM_BATCH = 65_536

__all__ = [
    "ROSTER_FILE_NAME",
    "ROSTER_MANIFEST_KIND",
    "ROSTER_SCHEMA",
    "ROSTER_SCHEMA_VERSION",
    "SNAPSHOT_CIK_INDEX_NAME",
    "SNAPSHOT_CIK_INDEX_SCHEMA",
    "Roster",
    "RosterError",
    "derive_roster_id",
    "empty_roster",
    "read_cik_index",
    "read_roster",
    "roster_to_csv_text",
    "write_cik_index",
    "write_roster",
    "write_roster_rows",
]

ROSTER_SCHEMA = pa.schema(
    [
        ("ordinal", pa.int64()),
        ("cik_padded", pa.string()),
        ("name", pa.string()),
    ]
)

SNAPSHOT_CIK_INDEX_SCHEMA = pa.schema([("cik", pa.string())])


class RosterError(ValueError):
    """Raised when a roster cannot be produced, stored, or verified."""


@dataclass(frozen=True, slots=True)
class Roster:
    """A reference to one cohort's dataset, with the identity it resolves to.

    ``row_count`` is carried rather than measured so a caller can size a plan
    without opening the file. ``dataset`` is ``None`` only for the empty cohort,
    which has an identity of its own and no rows to read.
    """

    roster_id: str
    row_count: int
    #: Where the rows live. Excluded from equality: a roster is named by what it
    #: contains, so the same cohort copied to another directory is the same roster,
    #: not a different one.
    dataset: Path | None = field(default=None, compare=False)

    @property
    def is_empty(self) -> bool:
        """True when the cohort holds no CIKs at all."""
        return self.row_count == 0

    def range_rows(self, start: int, length: int) -> tuple[tuple[str, str], ...]:
        """``(cik, name)`` pairs for one ordinal range, in cohort order.

        Only the row groups that can contain the range are read, so the cost is
        proportional to the slice rather than to the cohort.
        """
        if start < 0 or length < 0:
            raise RosterError(f"invalid roster range start={start} length={length}")
        if self.dataset is None or length == 0 or start >= self.row_count:
            return ()
        stop = min(start + length, self.row_count)

        handle = pq.ParquetFile(self.dataset)
        columns = ["ordinal", "cik_padded", "name"]
        collected: list[tuple[int, str, str]] = []
        for index in range(handle.metadata.num_row_groups):
            span = _row_group_span(handle, index)
            if span is not None and span[1] < start:
                continue
            if span is not None and span[0] >= stop:
                break
            table = handle.read_row_group(index, columns=columns)
            for ordinal, cik, name in zip(
                table.column("ordinal").to_pylist(),
                table.column("cik_padded").to_pylist(),
                table.column("name").to_pylist(),
                strict=True,
            ):
                if start <= ordinal < stop:
                    collected.append((int(ordinal), str(cik), str(name or "")))
        collected.sort(key=lambda row: row[0])
        return tuple((cik, name) for _, cik, name in collected)

    def range_ciks(self, start: int, length: int) -> tuple[str, ...]:
        """CIKs for one ordinal range; chunk membership is a range, not a list."""
        return tuple(cik for cik, _ in self.range_rows(start, length))

    def iter_rows(self) -> Iterator[tuple[str, str]]:
        """Stream every ``(cik, name)`` pair in cohort order, one batch at a time."""
        if self.dataset is None:
            return
        handle = pq.ParquetFile(self.dataset)
        columns = ["cik_padded", "name"]
        for batch in handle.iter_batches(batch_size=STREAM_BATCH, columns=columns):
            for cik, name in zip(
                batch.column("cik_padded").to_pylist(),
                batch.column("name").to_pylist(),
                strict=True,
            ):
                yield str(cik), str(name or "")

    def name_map(self) -> dict[str, str]:
        """Every curated display name keyed by CIK, built once for bulk lookup.

        This materializes the cohort, so it is for the one caller that folds a
        whole curated file against another dataset to build a published
        projection, not for per-CIK lookup. Callers needing a handful of names
        should read an ordinal range instead.
        """
        return dict(self.iter_rows())


def _row_group_span(handle: pq.ParquetFile, index: int) -> tuple[int, int] | None:
    """The ordinal range one row group covers, or ``None`` when unknowable.

    The cohort is written in ordinal order, so a row group's statistics bound
    which rows it holds. A writer that omits them yields ``None`` and the caller
    falls back to reading the file, which is slower but still correct.
    """
    statistics = handle.metadata.row_group(index).column(0).statistics
    if statistics is None or not statistics.has_min_max:
        return None
    return int(statistics.min), int(statistics.max)


def derive_roster_id(dataset: str | os.PathLike[str]) -> str:
    """Derive a roster's identity from its ordered dataset.

    Hashed row by row rather than through one canonical JSON document: a
    250,000-CIK roster would otherwise materialize a multi-megabyte string, and
    identity has to stay derivable at full-corpus scale. The rows are streamed
    from the dataset in batches, so the caller never holds the cohort either.
    """
    target = Path(dataset)
    if not target.is_file():
        raise FileNotFoundError(f"roster dataset not found: {target}")

    handle = pq.ParquetFile(target)
    # The prefix carries the row count, so it must be hashed before the rows it
    # counts. Parquet metadata supplies the count without reading any row.
    digest = hashlib.sha256()
    digest.update(
        canonical_json(
            [_ID_PREFIX, ROSTER_SCHEMA_VERSION, handle.metadata.num_rows]
        ).encode("utf-8")
    )
    columns = ["ordinal", "cik_padded", "name"]
    for batch in handle.iter_batches(batch_size=STREAM_BATCH, columns=columns):
        for ordinal, cik, name in zip(
            batch.column("ordinal").to_pylist(),
            batch.column("cik_padded").to_pylist(),
            batch.column("name").to_pylist(),
            strict=True,
        ):
            cik_text = str(cik)
            name_text = str(name or "")
            digest.update(
                f"{int(ordinal)}\x1f{len(cik_text)}\x1f{cik_text}"
                f"\x1f{len(name_text)}\x1f{name_text}\n".encode()
            )

    return digest.hexdigest()[:32]


def empty_roster() -> Roster:
    """The empty cohort, with a stable identity of its own.

    Augmentation has to be able to say "nothing new" without inventing an
    identity for it, and that statement must not collide with any real roster.
    """
    return Roster(roster_id=derive_empty_roster_id(), row_count=0)


def derive_empty_roster_id() -> str:
    """Identity of the cohort that holds no CIKs.

    Derived directly from the same prefix and length the streaming hash uses, so
    the empty roster is a value of the same function rather than a special case
    that could drift from it.
    """
    return hashlib.sha256(
        canonical_json([_ID_PREFIX, ROSTER_SCHEMA_VERSION, 0]).encode("utf-8")
    ).hexdigest()[:32]


def roster_to_table(rows: Iterable[tuple[str, str]]) -> pa.Table:
    """Build a roster dataset table from ``(cik, name)`` pairs in cohort order."""
    materialized = [
        {"ordinal": ordinal, "cik_padded": cik, "name": name}
        for ordinal, (cik, name) in enumerate(rows)
    ]
    return pa.Table.from_pylist(materialized, schema=ROSTER_SCHEMA)


def write_roster_rows(
    rows: Sequence[tuple[str, str]], path: str | os.PathLike[str]
) -> tuple[Roster, str]:
    """Write a cohort dataset from ordered pairs; return its roster and digest.

    This is the seam a producer compiles into: the cohort is written once, and
    everything downstream reads the dataset rather than the caller's rows. A CIK
    appearing twice would make the ordinal ambiguous and break both chunk
    membership and the identity, so it is refused here rather than published.
    """
    target = Path(path)
    seen: set[str] = set()
    for cik, _name in rows:
        if cik in seen:
            raise RosterError(f"cohort contains a duplicate CIK: {cik}")
        seen.add(cik)
    write_parquet_table(roster_to_table(rows), target)
    if not read_parquet_schema(target).equals(ROSTER_SCHEMA, check_metadata=False):
        raise RosterError(f"roster dataset schema drifted: {target}")
    return Roster(
        roster_id=derive_roster_id(target), row_count=len(rows), dataset=target
    ), file_sha256(target)


def write_roster(roster: Roster, path: str | os.PathLike[str]) -> str:
    """Publish one cohort's dataset to ``path``; return the artifact digest.

    The bytes are copied rather than re-encoded. A cohort compiled by DuckDB and the
    same cohort re-serialized by pyarrow hold identical rows and therefore the same
    identity, but they are different files. Rewriting would make the digest recorded
    beside the plan a function of which writer ran, and would spend a decode and
    encode of the largest object in the pipeline to learn nothing.

    A plan bundle carries its own copy so it can be copied to a worker machine on its
    own; this is that copy, staged and renamed so a failed publish leaves nothing
    half-written beside the manifest that names it.
    """
    target = Path(path)
    if roster.dataset is None:
        raise RosterError("the empty roster has no dataset to publish")
    if not roster.dataset.is_file():
        raise FileNotFoundError(f"roster dataset not found: {roster.dataset}")
    if roster.dataset.resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(f".{target.name}.tmp.{os.getpid()}")
        try:
            shutil.copyfile(roster.dataset, staged)
            os.replace(staged, target)
        finally:
            if staged.exists():
                staged.unlink()
    if not read_parquet_schema(target).equals(ROSTER_SCHEMA, check_metadata=False):
        raise RosterError(f"roster dataset schema drifted: {target}")
    if derive_roster_id(target) != roster.roster_id:
        raise RosterError(
            f"published roster at {target} does not carry identity {roster.roster_id}"
        )
    return file_sha256(target)


def read_roster(
    path: str | os.PathLike[str], *, expected_roster_id: str | None = None
) -> Roster:
    """Open a roster dataset and verify its schema and, when given, its identity.

    The identity is recomputed by streaming the file, so a cohort is proven
    without ever holding it.
    """
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"roster dataset not found: {target}")
    if not read_parquet_schema(target).equals(ROSTER_SCHEMA, check_metadata=False):
        raise RosterError(f"roster dataset schema drifted: {target}")

    row_count = pq.ParquetFile(target).metadata.num_rows
    roster = Roster(
        roster_id=derive_roster_id(target), row_count=row_count, dataset=target
    )
    if expected_roster_id is not None and roster.roster_id != expected_roster_id:
        raise RosterError(
            f"roster at {target} has identity {roster.roster_id!r}, "
            f"expected {expected_roster_id!r}"
        )
    return roster


def write_cik_index(ciks: Iterable[str], path: str | os.PathLike[str]) -> str:
    """Write a sorted distinct CIK index beside a published payload."""
    target = Path(path)
    ordered = sorted(set(ciks))
    if not ordered:
        raise RosterError("a published CIK index must not be empty")
    table = pa.Table.from_pylist(
        [{"cik": cik} for cik in ordered], schema=SNAPSHOT_CIK_INDEX_SCHEMA
    )
    write_parquet_table(table, target)
    if not read_parquet_schema(target).equals(
        SNAPSHOT_CIK_INDEX_SCHEMA, check_metadata=False
    ):
        raise RosterError(f"CIK index schema drifted: {target}")
    return file_sha256(target)


def read_cik_index(path: str | os.PathLike[str]) -> tuple[str, ...]:
    """Read a published CIK index and verify it is sorted and duplicate-free."""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"CIK index not found: {target}")
    if not read_parquet_schema(target).equals(
        SNAPSHOT_CIK_INDEX_SCHEMA, check_metadata=False
    ):
        raise RosterError(f"CIK index schema drifted: {target}")
    ciks = tuple(
        str(value) for value in pq.read_table(target).column("cik").to_pylist()
    )
    if list(ciks) != sorted(set(ciks)):
        raise RosterError(f"CIK index is not sorted and distinct: {target}")
    return ciks


def roster_to_csv_text(roster: Roster) -> str:
    """Render a roster as the ``cik,name`` CSV that people and scripts import.

    The CSV is an export format, not the internal carrier. It exists so the
    ``cik,name`` input contract keeps working while the roster dataset is what the
    planner actually reads. Rows are streamed from the dataset.
    """
    lines = ["cik,name"]
    for cik, name in roster.iter_rows():
        text = str(name or "")
        if any(character in text for character in (",", '"', "\n", "\r")):
            text = '"' + text.replace('"', '""') + '"'
        lines.append(f"{cik},{text}")
    return "\n".join(lines) + "\n"
