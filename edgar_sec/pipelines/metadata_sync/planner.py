"""Deterministic chunk planning over an immutable CIK roster.
Chunk membership is a range over roster ordinals, so the plan document stays
constant in cohort size. Identity covers the cohort and chunk layout only, never
assignment, worker count, or time.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.submissions.schemas import SCHEMA_VERSION
from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import arrow_table, connect
from edgar_sec.infra.storage.parquet import read_parquet_schema, write_parquet_table

from .paths import RunPaths
from .roster import (
    ROSTER_SCHEMA,
    Roster,
    RosterError,
    derive_roster_id,
    read_roster,
    write_roster,
)

if TYPE_CHECKING:
    from edgar_sec.infra.storage.bulk_archive import ArchiveReference, BulkArchiveStore

PLAN_FORMAT_VERSION = "2.1.0"
PLAN_MANIFEST_KIND = "metadata_plan"

_MAIN_MEMBER_RE = re.compile(r"^CIK(\d{10})\.json$")
_SHARD_MEMBER_RE = re.compile(r"^CIK(\d{10})-submissions-(\d+)\.json$")
FINGERPRINTS_SCHEMA = pa.schema(
    [("cik_padded", pa.string(), False), ("fingerprint", pa.string(), False)]
)

_ARCHIVE_FINGERPRINTS_SQL = r"""
WITH mains AS (
  SELECT substr(member_name, 4, 10) AS cik, crc32 AS main_crc
  FROM read_parquet(?) WHERE regexp_matches(member_name, '^CIK[0-9]{10}\.json$')
), shards AS (
  SELECT substr(member_name, 4, 10) AS cik,
         CAST(regexp_extract(member_name, '-submissions-([0-9]+)\.json$', 1)
              AS BIGINT) AS shard_no,
         crc32
  FROM read_parquet(?)
  WHERE regexp_matches(member_name, '^CIK[0-9]{10}-submissions-[0-9]+\.json$')
), shard_csv AS (
  SELECT cik, string_agg(CAST(crc32 AS VARCHAR), ',' ORDER BY shard_no) AS shard_crcs
  FROM shards GROUP BY cik
)
SELECT m.cik AS cik_padded,
       sha256('member-fingerprint-v1:' || m.cik || ':'
              || CAST(m.main_crc AS VARCHAR) || ':'
              || coalesce(s.shard_crcs, '')) AS fingerprint
FROM mains m LEFT JOIN shard_csv s ON s.cik = m.cik
ORDER BY m.cik
"""

_ARCHIVE_ROSTER_SQL = r"""
SELECT CAST(row_number() OVER (ORDER BY cik) - 1 AS BIGINT) AS ordinal,
       cik AS cik_padded, '' AS name
FROM (
  SELECT substr(member_name, 4, 10) AS cik
  FROM read_parquet(?) WHERE regexp_matches(member_name, '^CIK[0-9]{10}\.json$')
)
ORDER BY cik
"""

_ARCHIVE_MAIN_COUNT_SQL = r"""
SELECT count(*), count(DISTINCT substr(member_name, 4, 10))
FROM read_parquet(?) WHERE regexp_matches(member_name, '^CIK[0-9]{10}\.json$')
"""

__all__ = [
    "FINGERPRINTS_SCHEMA",
    "PLAN_FORMAT_VERSION",
    "PLAN_MANIFEST_KIND",
    "FingerprintIndex",
    "Plan",
    "build_archive_plan",
    "build_plan",
    "derive_plan_id",
    "load_plan",
    "member_fingerprints",
    "read_fingerprints",
    "roster_rows_from_member_index",
    "utc_now_iso",
    "write_fingerprints",
    "write_plan",
]


def utc_now_iso() -> str:
    """Current UTC time in second-resolution ISO 8601."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def derive_plan_id(
    roster_id: str,
    chunk_size: int,
    *,
    kind: str = "full",
    parent_id: str = "",
    plan_format_version: str = PLAN_FORMAT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    archive_sha256: str = "",
) -> str:
    """Derive a stable plan identifier from the plan-defining inputs.
    Assignment, worker count, and timestamps are excluded by construction.
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    material = ":".join(
        (
            "metadata-plan-v2",
            plan_format_version,
            schema_version,
            kind,
            parent_id,
            roster_id,
            str(chunk_size),
            archive_sha256,
        )
    )
    return sha256_bytes(material.encode("utf-8"))[:16]


@dataclass(frozen=True, slots=True)
class Plan:
    """An immutable fetch plan: a cohort, a chunk layout, and a lineage.
    Chunks are ranges, so membership is arithmetic rather than a carried list.
    """

    plan_id: str
    roster: Roster
    chunk_size: int
    kind: str = "full"
    parent_id: str = ""
    created_at: str = ""
    input_name: str = ""
    input_fingerprint: str = ""
    plan_format_version: str = PLAN_FORMAT_VERSION
    schema_version: str = SCHEMA_VERSION
    roster_sha256: str = ""
    selected_limit: int | None = None
    archive_source_id: str = ""
    archive_sha256: str = ""

    @property
    def is_archive_plan(self) -> bool:
        """True when this plan's roster and fingerprints come from a bulk archive."""
        return bool(self.archive_sha256)

    @property
    def row_count(self) -> int:
        """Number of CIKs this plan covers."""
        return self.roster.row_count

    def lineage(self) -> dict[str, str]:
        """Identity a plan carries into its snapshot's publication record."""
        recorded: dict[str, str] = {}
        if self.parent_id:
            recorded["parent_snapshot_id"] = self.parent_id
        if self.archive_source_id:
            recorded["archive_source_id"] = self.archive_source_id
        if self.archive_sha256:
            recorded["archive_sha256"] = self.archive_sha256
        return recorded

    @property
    def chunk_count(self) -> int:
        """Number of chunks the roster is split into."""
        return -(-self.roster.row_count // self.chunk_size)

    def chunk_id_of(self, ordinal: int) -> int:
        """Chunk containing a zero-based roster ordinal."""
        if ordinal < 0 or ordinal >= self.roster.row_count:
            raise RosterError(f"ordinal {ordinal} is outside the roster")
        return ordinal // self.chunk_size

    def chunk_start(self, chunk_id: int) -> int:
        """First roster ordinal in one chunk."""
        self._require_chunk(chunk_id)
        return chunk_id * self.chunk_size

    def chunk_length(self, chunk_id: int) -> int:
        """Number of roster ordinals in one chunk."""
        self._require_chunk(chunk_id)
        start = chunk_id * self.chunk_size
        return max(0, min(self.chunk_size, self.roster.row_count - start))

    def chunk_ciks(self, chunk_id: int) -> tuple[str, ...]:
        """CIKs one chunk covers, in plan order."""
        start = self.chunk_start(chunk_id)
        return self.roster.range_ciks(start, self.chunk_length(chunk_id))

    def chunk_ids(self) -> list[int]:
        """Every planned chunk id, ascending."""
        return list(range(self.chunk_count))

    def _require_chunk(self, chunk_id: int) -> None:
        if chunk_id < 0 or chunk_id >= self.chunk_count:
            raise RosterError(
                f"chunk {chunk_id} is not present in plan {self.plan_id} "
                f"(0..{self.chunk_count - 1})"
            )

    def to_manifest(self) -> dict[str, Any]:
        """Serialize the small execution manifest for this plan.

        Constant in the cohort size; the cohort lives in the referenced dataset.
        """
        return {
            "manifest_kind": PLAN_MANIFEST_KIND,
            "plan_id": self.plan_id,
            "plan_format_version": self.plan_format_version,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "kind": self.kind,
            "parent_snapshot_id": self.parent_id,
            "roster_id": self.roster.roster_id,
            "roster_row_count": self.roster.row_count,
            "roster_artifact_sha256": self.roster_sha256,
            "chunk_size": self.chunk_size,
            "chunk_count": self.chunk_count,
            "row_count": self.row_count,
            "input_name": self.input_name,
            "input_fingerprint": self.input_fingerprint,
            "selected_limit": self.selected_limit,
            "archive_source_id": self.archive_source_id,
            "archive_sha256": self.archive_sha256,
        }


def build_plan(
    roster: Roster,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    kind: str = "full",
    parent_id: str = "",
    input_name: str = "",
    input_fingerprint: str = "",
    created_at: str | None = None,
    selected_limit: int | None = None,
    archive_source_id: str = "",
    archive_sha256: str = "",
) -> Plan:
    """Build the immutable plan for a selected roster."""
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    if roster.is_empty:
        raise RosterError("a plan requires a non-empty roster")
    return Plan(
        plan_id=derive_plan_id(
            roster.roster_id,
            chunk_size,
            kind=kind,
            parent_id=parent_id,
            archive_sha256=archive_sha256,
        ),
        roster=roster,
        chunk_size=chunk_size,
        kind=kind,
        parent_id=parent_id,
        created_at=created_at or utc_now_iso(),
        input_name=input_name,
        input_fingerprint=input_fingerprint,
        selected_limit=selected_limit,
        archive_source_id=archive_source_id,
        archive_sha256=archive_sha256,
    )


def _parse_member_index(
    index: pa.Table,
) -> tuple[dict[str, int], dict[str, list[tuple[int, int]]]]:
    mains: dict[str, int] = {}
    shards: dict[str, list[tuple[int, int]]] = {}
    names = index.column("member_name").to_pylist()
    crcs = index.column("crc32").to_pylist()
    for name, crc in zip(names, crcs, strict=True):
        main = _MAIN_MEMBER_RE.fullmatch(str(name))
        if main:
            mains[main.group(1)] = int(crc)
            continue
        shard = _SHARD_MEMBER_RE.fullmatch(str(name))
        if shard:
            shards.setdefault(shard.group(1), []).append(
                (int(shard.group(2)), int(crc))
            )
    return mains, shards


def roster_rows_from_member_index(index: pa.Table) -> list[tuple[str, str]]:
    """Roster rows for an archive: every CIK with a main member, CIK-sorted.

    The archive carries no display names, so names publish empty, as the
    mutual-fund ticker source already does.
    """
    mains, _shards = _parse_member_index(index)
    return [(cik, "") for cik in sorted(mains)]


def member_fingerprints(index: pa.Table) -> dict[str, str]:
    """Per-CIK input fingerprint from member CRCs (main plus shards).

    A CIK's fingerprint changes exactly when one of its archive members
    changes, which is what makes CRC carry-forward sound.
    """
    mains, shards = _parse_member_index(index)
    fingerprints: dict[str, str] = {}
    for cik, main_crc in mains.items():
        shard_crcs = ",".join(str(crc) for _number, crc in sorted(shards.get(cik, [])))
        material = f"member-fingerprint-v1:{cik}:{main_crc}:{shard_crcs}"
        fingerprints[cik] = sha256_bytes(material.encode("utf-8"))
    return fingerprints


def write_fingerprints(fingerprints: Mapping[str, str], path: Path) -> str:
    """Write the per-CIK fingerprint dataset beside a plan; return its digest."""
    ordered = sorted(fingerprints)
    table = pa.table(
        {
            "cik_padded": ordered,
            "fingerprint": [fingerprints[cik] for cik in ordered],
        },
        schema=FINGERPRINTS_SCHEMA,
    )
    write_parquet_table(table, path)
    return file_sha256(path)


def read_fingerprints(path: Path) -> dict[str, str]:
    """Read a plan's per-CIK fingerprint dataset."""
    from edgar_sec.infra.storage.parquet import read_parquet_table

    table = read_parquet_table(path)
    return {
        str(cik): str(fingerprint)
        for cik, fingerprint in zip(
            table.column("cik_padded").to_pylist(),
            table.column("fingerprint").to_pylist(),
            strict=True,
        )
    }


class FingerprintIndex(Mapping[str, str]):
    """Per-CIK fingerprints read from a plan dataset one row group at a time.

    The dataset is CIK-sorted, so the row groups a lookup can touch are
    known from footer statistics; only the group a lookup lands in is read.
    """

    def __init__(self, path: Path) -> None:
        self._handle = pq.ParquetFile(path)
        self._spans = [
            self._group_span(index)
            for index in range(self._handle.metadata.num_row_groups)
        ]
        self._cached_group: int | None = None
        self._cached: dict[str, str] = {}

    def __len__(self) -> int:
        return self._handle.metadata.num_rows

    def __iter__(self) -> Iterator[str]:
        for batch in self._handle.iter_batches(
            batch_size=resolve_parquet_read_batch_size(), columns=["cik_padded"]
        ):
            yield from (str(value) for value in batch.column("cik_padded").to_pylist())

    def __getitem__(self, cik: str) -> str:
        value = self.get(cik)
        if value is None:
            raise KeyError(cik)
        return value

    def get(self, cik: str, default: str | None = None) -> str | None:
        """One CIK's fingerprint, or ``default`` when the CIK is unplanned."""
        for group in self._candidates(cik):
            if group != self._cached_group:
                self._load_group(group)
            if cik in self._cached:
                return self._cached[cik]
        return default

    def _candidates(self, cik: str) -> list[int]:
        return [
            index
            for index, span in enumerate(self._spans)
            if span is None or span[0] <= cik <= span[1]
        ]

    def _group_span(self, index: int) -> tuple[str, str] | None:
        column = self._handle.schema_arrow.get_field_index("cik_padded")
        statistics = self._handle.metadata.row_group(index).column(column).statistics
        if statistics is None or not statistics.has_min_max:
            return None
        return str(statistics.min), str(statistics.max)

    def _load_group(self, group: int) -> None:
        table = self._handle.read_row_group(
            group, columns=["cik_padded", "fingerprint"]
        )
        self._cached = {
            str(cik): str(fingerprint)
            for cik, fingerprint in zip(
                table.column("cik_padded").to_pylist(),
                table.column("fingerprint").to_pylist(),
                strict=True,
            )
        }
        self._cached_group = group


def build_archive_plan(
    store: "BulkArchiveStore",
    reference: "ArchiveReference",
    *,
    chunk_size: int,
    roster_dataset_path: Path,
    fingerprints_dataset_path: Path | None = None,
) -> tuple[Plan, Path]:
    """Build a full plan over a stored archive's membership.

    The plan identity binds the archive digest, so a new night's archive
    is a new plan; both datasets are computed in DuckDB, never as dicts.
    """
    fingerprints_path = fingerprints_dataset_path or roster_dataset_path.with_name(
        "fingerprints.parquet"
    )
    index_path = str(reference.member_index_path)
    con = connect()
    try:
        main_count, distinct_ciks = con.execute(
            _ARCHIVE_MAIN_COUNT_SQL, [index_path]
        ).fetchone()
        if int(main_count) != int(distinct_ciks):
            raise RosterError("archive member index holds a duplicate CIK main")
        roster_table = arrow_table(
            con, _ARCHIVE_ROSTER_SQL, params=[index_path], schema=ROSTER_SCHEMA
        )
        fingerprint_table = arrow_table(
            con,
            _ARCHIVE_FINGERPRINTS_SQL,
            params=[index_path, index_path],
            schema=FINGERPRINTS_SCHEMA,
        )
    finally:
        con.close()
    write_parquet_table(roster_table, roster_dataset_path)
    if not read_parquet_schema(roster_dataset_path).equals(
        ROSTER_SCHEMA, check_metadata=False
    ):
        raise RosterError(f"roster dataset schema drifted: {roster_dataset_path}")
    roster = Roster(
        roster_id=derive_roster_id(roster_dataset_path),
        row_count=roster_table.num_rows,
        dataset=Path(roster_dataset_path),
    )
    write_parquet_table(fingerprint_table, fingerprints_path)
    plan = build_plan(
        roster,
        chunk_size=chunk_size,
        kind="full",
        input_name=f"archive:{reference.source_id}",
        input_fingerprint=reference.sha256,
        archive_source_id=reference.source_id,
        archive_sha256=reference.sha256,
    )
    return plan, fingerprints_path


def _publish_fingerprints(source: Path, target: Path) -> str:
    """Publish a fingerprint dataset beside a plan; return its digest.

    Bytes are copied, not re-encoded, matching the roster's treatment.
    """
    if not read_parquet_schema(source).equals(
        FINGERPRINTS_SCHEMA, check_metadata=False
    ):
        raise RosterError(f"fingerprint dataset schema drifted: {source}")
    if source.resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(f".{target.name}.tmp.{os.getpid()}")
        try:
            shutil.copyfile(source, staged)
            os.replace(staged, target)
        finally:
            if staged.exists():
                staged.unlink()
    return file_sha256(target)


def write_plan(
    plan: Plan,
    run_paths: RunPaths,
    *,
    member_fingerprint_map: Mapping[str, str] | None = None,
    member_fingerprints_path: Path | None = None,
) -> str:
    """Write the plan bundle: roster dataset, execution manifest, input manifest.
    The roster is written and digested first, so a manifest never references a
    cohort that is not beside it.
    """
    digest = write_roster(plan.roster, run_paths.roster_file)
    manifest = plan.to_manifest()
    manifest["roster_artifact_sha256"] = digest
    if member_fingerprints_path is not None:
        manifest["member_fingerprints_sha256"] = _publish_fingerprints(
            member_fingerprints_path, run_paths.fingerprints_file
        )
    elif member_fingerprint_map is not None:
        manifest["member_fingerprints_sha256"] = write_fingerprints(
            member_fingerprint_map, run_paths.fingerprints_file
        )
    atomic_write_json(run_paths.plan_file, manifest, canonical=False, indent=2)
    atomic_write_json(
        run_paths.input_manifest_file,
        {
            "input_name": plan.input_name,
            "input_fingerprint": plan.input_fingerprint,
            "selected_limit": plan.selected_limit,
            "roster_id": plan.roster.roster_id,
            "roster_row_count": plan.roster.row_count,
        },
        canonical=False,
        indent=2,
    )
    return digest


def load_plan(run_paths: RunPaths) -> Plan:
    """Load and validate a written plan bundle.
    A plan whose recorded inputs do not reproduce its id is rejected, not reused.
    """
    path = run_paths.plan_file
    if not path.is_file():
        raise FileNotFoundError(f"missing plan: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"plan is not a JSON object: {path}")
    if manifest.get("manifest_kind") != PLAN_MANIFEST_KIND:
        raise ValueError(
            f"incompatible plan at {path}: manifest_kind is "
            f"{manifest.get('manifest_kind')!r}, this build requires "
            f"{PLAN_MANIFEST_KIND!r}; regenerate the plan"
        )
    _check_version(manifest, "plan_format_version", PLAN_FORMAT_VERSION, path)
    _check_version(manifest, "schema_version", SCHEMA_VERSION, path)

    roster = read_roster(
        run_paths.roster_file, expected_roster_id=str(manifest.get("roster_id", ""))
    )
    chunk_size = int(manifest.get("chunk_size", 0))
    kind = str(manifest.get("kind", "full"))
    parent_id = str(manifest.get("parent_snapshot_id", ""))
    archive_sha256 = str(manifest.get("archive_sha256", ""))
    expected = derive_plan_id(
        roster.roster_id,
        chunk_size,
        kind=kind,
        parent_id=parent_id,
        plan_format_version=str(manifest.get("plan_format_version", "")),
        schema_version=str(manifest.get("schema_version", "")),
        archive_sha256=archive_sha256,
    )
    if manifest.get("plan_id") != expected:
        raise ValueError(
            f"stale plan at {path}: plan_id {manifest.get('plan_id')!r} does not "
            f"match its recorded inputs (expected {expected!r}); regenerate the plan"
        )
    if int(manifest.get("row_count", -1)) != roster.row_count:
        raise ValueError(
            f"corrupt plan at {path}: row_count {manifest.get('row_count')!r} "
            f"does not match the roster's {roster.row_count} CIKs"
        )

    limit = manifest.get("selected_limit")
    return Plan(
        plan_id=expected,
        roster=roster,
        chunk_size=chunk_size,
        kind=kind,
        parent_id=parent_id,
        created_at=str(manifest.get("created_at", "")),
        input_name=str(manifest.get("input_name", "")),
        input_fingerprint=str(manifest.get("input_fingerprint", "")),
        plan_format_version=PLAN_FORMAT_VERSION,
        schema_version=SCHEMA_VERSION,
        roster_sha256=str(manifest.get("roster_artifact_sha256", "")),
        selected_limit=int(limit) if isinstance(limit, int) else None,
        archive_source_id=str(manifest.get("archive_source_id", "")),
        archive_sha256=archive_sha256,
    )


def _check_version(manifest: dict, key: str, expected: str, path: Path) -> None:
    """Reject a plan whose recorded version the current code no longer honours."""
    recorded = manifest.get(key)
    if recorded != expected:
        raise ValueError(
            f"incompatible plan at {path}: {key} is {recorded!r}, this build "
            f"requires {expected!r}; regenerate the plan"
        )
