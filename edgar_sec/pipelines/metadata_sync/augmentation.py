"""Delta augmentation against a published snapshot.

Augmentation plans work only for CIKs the base snapshot does not already
contain. The published base is never refetched: delta chunks are merged with
the existing snapshot Parquet, so a snapshot that already holds N CIKs and
receives K new ones ends with N+K rows and only K network fetches.

Identity is the load-bearing decision here. A delta plan is identified by its
base snapshot *and* its delta roster, never by the request file that named the
CIKs. The same requested list against two different bases is two different
deltas, and the earlier request-fingerprinted identity gave both the same plan
directory and let one overwrite the other's record.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.infra.storage.duckdb import (
    concat_to_parquet,
    connect,
    find_duplicate_keys,
    find_duplicate_nested_values,
    find_null_keys,
)
from edgar_sec.infra.storage.parquet import (
    count_parquet_rows,
    read_parquet_schema,
    read_parquet_table,
)

from .manifest import InputManifest, read_cik_manifest
from .merger import MergeError, MergeReport, publish_cik_index, publish_snapshot
from .paths import MetadataPaths, resolve_run_paths
from .planner import Plan, build_plan, utc_now_iso, write_plan
from .roster import (
    Roster,
    build_roster,
    read_cik_index,
    roster_from_manifest,
    union_rosters,
    without_ciks,
)
from .sec_client import SubmissionsClient
from .worker import run_chunk_ids

__all__ = [
    "AugmentResult",
    "augment",
    "augment_from_manifest",
    "augment_from_roster",
    "base_snapshot_ciks",
    "derive_delta_plan",
    "snapshot_cik_roster",
]


@dataclass(frozen=True, slots=True)
class AugmentResult:
    """Outcome of one augmentation run."""

    base_snapshot_id: str
    new_snapshot_id: str
    base_row_count: int
    delta_row_count: int
    refetched_ciks: tuple[str, ...]
    report: MergeReport

    @property
    def total_row_count(self) -> int:
        """Rows in the newly published snapshot."""
        return self.report.row_count


def snapshot_cik_roster(
    metadata_paths: MetadataPaths,
    snapshot_id: str,
    *,
    names: dict[str, str] | None = None,
) -> Roster:
    """Read the CIK set already present in a published snapshot.

    The published index is read when one exists, because it is the artifact the
    snapshot claims to hold. A snapshot published before the index existed falls
    back to projecting the payload's CIK column, and a missing base is still an
    error: an unreadable base must never be mistaken for an empty one.
    """
    index_path = metadata_paths.snapshot_cik_index(snapshot_id)
    if index_path.is_file():
        ciks = read_cik_index(index_path)
    else:
        payload = metadata_paths.snapshot_file(snapshot_id)
        if not payload.is_file():
            raise FileNotFoundError(f"base snapshot not found: {payload}")
        table = read_parquet_table(payload, columns=["cik"])
        ciks = tuple(str(value) for value in table.column("cik").to_pylist() if value)
    if names:
        return build_roster(
            sorted(set(ciks)), [names.get(cik, "") for cik in sorted(set(ciks))]
        )
    return build_roster(sorted(set(ciks)))


def base_snapshot_ciks(metadata_paths: MetadataPaths, snapshot_id: str) -> set[str]:
    """Read the CIK set already present in a published snapshot."""
    return set(snapshot_cik_roster(metadata_paths, snapshot_id).ciks)


def derive_delta_plan(
    requested: Roster,
    base: Roster,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    base_snapshot_id: str = "",
    input_name: str = "",
    input_fingerprint: str = "",
    created_at: str | None = None,
) -> Plan:
    """Build the plan covering exactly the CIKs absent from the base snapshot."""
    delta = without_ciks(requested, base.ciks)
    if delta.is_empty:
        raise MergeError(
            "augmentation requested no work: every requested CIK is already "
            f"present in base snapshot {base_snapshot_id}"
        )
    return build_plan(
        delta,
        chunk_size=chunk_size,
        kind="delta",
        parent_id=base_snapshot_id,
        input_name=input_name,
        input_fingerprint=input_fingerprint,
        created_at=created_at,
    )


def augment(
    client: SubmissionsClient,
    manifest: InputManifest,
    metadata_paths: MetadataPaths,
    *,
    base_snapshot_id: str,
    new_snapshot_id: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    workers: int | None = None,
    lineage: dict[str, str] | None = None,
) -> AugmentResult:
    """Augment a published snapshot with any newly requested CIKs.

    The base snapshot file is merged alongside the delta checkpoints, so base
    CIKs are carried forward untouched and are never refetched. Copied base rows
    keep their original row-level ``snapshot_id``: that field is row provenance,
    not the identity of whichever artifact later contains the row, and rewriting
    it would misstate where the data came from.
    """
    base_path = metadata_paths.snapshot_file(base_snapshot_id)
    if not base_path.is_file():
        raise FileNotFoundError(f"base snapshot not found: {base_path}")
    base = snapshot_cik_roster(metadata_paths, base_snapshot_id)
    base_rows = count_parquet_rows(base_path)

    plan = derive_delta_plan(
        roster_from_manifest(manifest),
        base,
        chunk_size=chunk_size,
        base_snapshot_id=base_snapshot_id,
        input_name=manifest.input_name,
        input_fingerprint=manifest.input_fingerprint,
    )
    run_paths = resolve_run_paths(plan.plan_id, metadata_paths.artifacts_root)
    write_plan(plan, run_paths)

    results = run_chunk_ids(
        client,
        plan,
        run_paths,
        plan.chunk_ids(),
        snapshot_id=new_snapshot_id,
        workers=workers,
    )
    refetched: list[str] = []
    for result in results:
        if not result.skipped_existing:
            refetched.extend(plan.chunk_ciks(result.chunk_id))

    delta_paths = [str(run_paths.chunk_file(chunk_id)) for chunk_id in plan.chunk_ids()]
    inputs = [str(base_path), *delta_paths]
    output_path = metadata_paths.snapshot_file(new_snapshot_id)

    report = MergeReport(
        snapshot_id=new_snapshot_id,
        chunk_count=plan.chunk_count,
        plan_id=plan.plan_id,
        input_fingerprint=plan.input_fingerprint,
        kind=plan.kind,
        parent_snapshot_id=base_snapshot_id,
        roster_id=plan.roster.roster_id,
        delta_roster_id=plan.roster.roster_id,
        registry_id=(lineage or {}).get("registry_id", ""),
        source_snapshot_id=(lineage or {}).get("source_snapshot_id", ""),
    )

    con = connect()
    try:
        if find_null_keys(con, inputs, "cik"):
            raise MergeError("augmentation rejected: null CIK in merged inputs")
        duplicates = find_duplicate_keys(con, inputs, "cik")
        if duplicates:
            raise MergeError(
                f"augmentation rejected: CIKs appear in both base and delta: "
                f"{duplicates}"
            )
        report.duplicate_accessions = find_duplicate_nested_values(
            con, inputs, "filings", "accession_number"
        )
        if report.duplicate_accessions:
            report.warnings.append(
                f"{len(report.duplicate_accessions)} duplicate accession(s) observed; "
                "accession is not globally unique"
            )
        row_count = concat_to_parquet(con, inputs, output_path, order_by=("cik",))
    finally:
        con.close()

    expected = base_rows + plan.row_count
    if row_count != expected:
        raise MergeError(
            f"augmentation rejected: merged row count {row_count} "
            f"!= expected {expected} ({base_rows} base + {plan.row_count} delta)"
        )
    if not read_parquet_schema(output_path).equals(
        SUBMISSION_METADATA_SCHEMA, check_metadata=False
    ):
        raise MergeError("augmentation rejected: published artifact schema drifted")

    merged = snapshot_cik_roster(metadata_paths, new_snapshot_id)
    expected_ciks = union_rosters(base, plan.roster)
    if set(merged.ciks) != set(expected_ciks.ciks):
        raise MergeError("augmentation rejected: merged CIK set differs from union")

    report.row_count = row_count
    report.output_path = str(output_path)
    report.artifact_sha256 = file_sha256(output_path)
    publish_cik_index(report, metadata_paths, expected_ciks.ciks)
    report.merged_at = utc_now_iso()
    publish_snapshot(report, metadata_paths)

    return AugmentResult(
        base_snapshot_id=base_snapshot_id,
        new_snapshot_id=new_snapshot_id,
        base_row_count=base_rows,
        delta_row_count=plan.row_count,
        refetched_ciks=tuple(refetched),
        report=report,
    )


def augment_from_roster(
    client: SubmissionsClient,
    requested: Roster,
    metadata_paths: MetadataPaths,
    *,
    base_snapshot_id: str,
    new_snapshot_id: str,
    **kwargs: Any,
) -> AugmentResult:
    """Augment from an already-resolved roster rather than a manifest file."""
    return augment(
        client,
        InputManifest(
            input_name=kwargs.pop("input_name", ""),
            input_path=Path("."),
            input_fingerprint=kwargs.pop("input_fingerprint", ""),
            ciks=requested.ciks,
            names=requested.names,
        ),
        metadata_paths,
        base_snapshot_id=base_snapshot_id,
        new_snapshot_id=new_snapshot_id,
        **kwargs,
    )


def augment_from_manifest(
    client: SubmissionsClient,
    input_path: str,
    metadata_paths: MetadataPaths,
    **kwargs: Any,
) -> AugmentResult:
    """Convenience wrapper reading the manifest from disk before augmenting."""
    manifest = read_cik_manifest(input_path)
    return augment(client, manifest, metadata_paths, **kwargs)
