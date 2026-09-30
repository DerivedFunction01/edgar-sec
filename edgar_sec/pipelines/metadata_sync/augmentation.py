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

The published snapshot follows the same rule. ``new_snapshot_id`` defaults to
the delta plan id, which is already a content address over the base snapshot, the
effective delta roster, and the chunk layout, so an augmentation is idempotent
and needs no identifier typed by an operator. An explicit id remains an override
for the distribution path, where a worker stamps rows with the snapshot the
coordinator will publish under. This mirrors ``RunOptions.effective_snapshot_id``
for a full ingest, and it is the reason every other Phase 1 artifact is
content-addressed and this one is not required to be.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.infra.storage.duckdb import (
    connect,
    find_duplicate_keys,
    find_duplicate_nested_values,
    find_null_keys,
)
from edgar_sec.infra.storage.parquet import read_parquet_table

from .manifest import InputManifest, read_cik_manifest
from .merger import (
    MergeError,
    MergeReport,
    _filing_record_count,
    _published_ciks,
    parts_digest,
    publish_cik_index,
    publish_parts,
    publish_snapshot,
)
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
from .snapshot import read_snapshot_parts
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
    back to projecting the CIK column of every part its manifest lists, and a
    missing base is still an error: an unreadable base must never be mistaken for
    an empty one.
    """
    index_path = metadata_paths.snapshot_cik_index(snapshot_id)
    if index_path.is_file():
        ciks = read_cik_index(index_path)
    else:
        parts = read_snapshot_parts(metadata_paths.snapshot_manifest(snapshot_id))
        ciks = tuple(
            str(value)
            for value in (
                value
                for path in parts.paths
                for value in read_parquet_table(path, columns=["cik"])
                .column("cik")
                .to_pylist()
                if value
            )
        )
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
    new_snapshot_id: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    workers: int | None = None,
    lineage: dict[str, str] | None = None,
) -> AugmentResult:
    """Augment a published snapshot with any newly requested CIKs.

    The base snapshot is read as the ordered part list its manifest declares, so a
    multipart base contributes all of its parts and a legacy single-file base
    contributes one. Delta chunks are published as the remaining parts of the new
    snapshot, so base CIKs are carried forward untouched and never refetched.

    Copied base rows keep their original row-level ``snapshot_id``: that field is
    row provenance, not the identity of whichever artifact later contains the row,
    and rewriting it would misstate where the data came from.

    An empty ``new_snapshot_id`` resolves to the delta plan id once the plan is
    derived, so the published identity is derived rather than supplied.
    """
    base_parts = read_snapshot_parts(metadata_paths.snapshot_manifest(base_snapshot_id))
    base = snapshot_cik_roster(metadata_paths, base_snapshot_id)
    base_rows = (
        sum(int(part["row_count"]) for part in base_parts.layout.manifest["parts"])
        if base_parts.layout.multipart
        else base_parts.row_count
    )

    plan = derive_delta_plan(
        roster_from_manifest(manifest),
        base,
        chunk_size=chunk_size,
        base_snapshot_id=base_snapshot_id,
        input_name=manifest.input_name,
        input_fingerprint=manifest.input_fingerprint,
    )
    resolved_snapshot_id = new_snapshot_id or plan.plan_id
    run_paths = resolve_run_paths(plan.plan_id, metadata_paths.artifacts_root)
    write_plan(plan, run_paths)

    results = run_chunk_ids(
        client,
        plan,
        run_paths,
        plan.chunk_ids(),
        snapshot_id=resolved_snapshot_id,
        workers=workers,
    )
    refetched: list[str] = []
    for result in results:
        if not result.skipped_existing:
            refetched.extend(plan.chunk_ciks(result.chunk_id))

    delta_paths = [str(run_paths.chunk_file(chunk_id)) for chunk_id in plan.chunk_ids()]
    inputs = [str(path) for path in base_parts.paths]
    inputs.extend(delta_paths)

    report = MergeReport(
        snapshot_id=resolved_snapshot_id,
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
    finally:
        con.close()

    sources: list[tuple[str, Path]] = [
        (f"base:{base_snapshot_id}#{index}", path)
        for index, path in enumerate(base_parts.paths)
    ]
    sources.extend(
        (f"chunk:{path.stem}", path)
        for path in (run_paths.chunk_file(chunk_id) for chunk_id in plan.chunk_ids())
    )
    part_paths = publish_parts(report, metadata_paths, sources)

    row_count = sum(int(part["row_count"]) for part in report.parts)
    expected = base_rows + plan.row_count
    if row_count != expected:
        raise MergeError(
            f"augmentation rejected: published row count {row_count} "
            f"!= expected {expected} ({base_rows} base + {plan.row_count} delta)"
        )

    report.row_count = row_count
    report.parts_digest = parts_digest(report.parts)
    report.filing_record_count = _filing_record_count([str(p) for p in part_paths])
    merged = _published_ciks(part_paths)
    expected_ciks = union_rosters(base, plan.roster)
    if set(merged) != set(expected_ciks.ciks):
        raise MergeError("augmentation rejected: merged CIK set differs from union")

    publish_cik_index(report, metadata_paths, merged)
    report.merged_at = utc_now_iso()
    publish_snapshot(report, metadata_paths)

    return AugmentResult(
        base_snapshot_id=base_snapshot_id,
        new_snapshot_id=resolved_snapshot_id,
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
    new_snapshot_id: str = "",
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
