"""Delta augmentation against a published snapshot.

Augmentation plans work only for CIKs the base snapshot does not already
contain. The published base is never refetched: delta chunks are merged with the
existing snapshot Parquet, so a snapshot that already holds N CIKs and receives K
new ones ends with N+K rows and only K network fetches.

Identity is the load-bearing decision here. A delta plan is identified by its base
snapshot *and* its delta roster, never by the request file that named the CIKs:
the same requested list against two different bases is two different deltas.
``new_snapshot_id`` defaults to the delta plan id, already a content address over
the base snapshot, the effective delta roster, and the chunk layout, so an
augmentation is idempotent and needs no identifier typed by an operator. An
explicit id remains an override for the distribution path, where a worker stamps
rows with the snapshot the coordinator will publish under.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.infra.storage.duckdb import (
    connect,
    find_duplicate_keys,
    find_null_keys,
)
from edgar_sec.infra.storage.parquet import read_parquet_table

from .manifest import InputManifest, read_cik_manifest
from .merger import (
    MergeError,
    MergeReport,
    _filing_record_count,
    _published_ciks,
    _safe_progress,
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
from .validation import find_duplicate_accessions
from .worker import run_chunk_ids

__all__ = [
    "AugmentPreflight",
    "AugmentResult",
    "augment",
    "augment_from_manifest",
    "augment_from_roster",
    "base_snapshot_ciks",
    "derive_delta_plan",
    "preflight_augment",
    "snapshot_cik_roster",
]


@dataclass(frozen=True, slots=True)
class AugmentPreflight:
    """What an augmentation would do, decided before anything is fetched.

    Separating this from the run is the point. "How many CIKs does the chosen
    cohort add to the chosen base?" is answerable from two published artifacts,
    so answering it before the client exists means the common boring outcome --
    the base already covers the request -- costs no network request, no
    rate-limit budget, and no published delta plan, and it reads as a result
    rather than as a failure.
    """

    base_snapshot_id: str
    requested: Roster
    base: Roster
    delta: Roster

    @property
    def is_empty(self) -> bool:
        """True when the base already holds every requested CIK."""
        return self.delta.is_empty

    @property
    def requested_count(self) -> int:
        return self.requested.row_count

    @property
    def already_present_count(self) -> int:
        return self.requested_count - self.delta.row_count

    def describe(self) -> str:
        """One operator-facing line describing the pending work."""
        return (
            f"{self.requested_count:,} requested, "
            f"{self.already_present_count:,} already in base {self.base_snapshot_id}, "
            f"{self.delta.row_count:,} to fetch"
        )


@dataclass(frozen=True, slots=True)
class AugmentResult:
    """Outcome of one augmentation run.

    ``report`` is ``None`` for a no-op: nothing was published, so there is no
    merge report, and returning an empty one would describe a publication that did
    not happen. ``no_op`` is therefore the field to branch on, and
    ``total_row_count`` reports the unchanged base rather than a fabricated total.
    """

    base_snapshot_id: str
    new_snapshot_id: str
    base_row_count: int
    delta_row_count: int
    refetched_ciks: tuple[str, ...]
    report: MergeReport | None
    no_op: bool = False
    requested_cik_count: int = 0
    already_present_count: int = 0

    @property
    def total_row_count(self) -> int:
        """Rows in the newly published snapshot, or in the unchanged base."""
        return self.report.row_count if self.report is not None else self.base_row_count


def preflight_augment(
    requested: Roster,
    metadata_paths: MetadataPaths,
    *,
    base_snapshot_id: str,
) -> AugmentPreflight:
    """Decide what an augmentation would fetch, reading only published artifacts.

    Every cohort is treated as a *requested* set and reduced against the base,
    including one that is already called a delta. An operator who points this at a
    hand-built increment, or re-runs an augmentation that already succeeded, gets
    the correct answer either way, and a request that the base already satisfies
    is reported as no work rather than refused.
    """
    base = snapshot_cik_roster(metadata_paths, base_snapshot_id)
    return AugmentPreflight(
        base_snapshot_id=base_snapshot_id,
        requested=requested,
        base=base,
        delta=without_ciks(requested, base.ciks),
    )


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
    preflight: AugmentPreflight | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> AugmentResult:
    """Augment a published snapshot with any newly requested CIKs.

    The base is read as the ordered part list its manifest declares, so a
    multipart base contributes all its parts and a legacy single-file base one.
    Delta chunks become the remaining parts of the new snapshot, so base CIKs are
    carried forward untouched and never refetched. Copied base rows keep their
    original row-level ``snapshot_id`` -- row provenance, not the identity of
    whichever artifact later contains the row -- and an empty
    ``new_snapshot_id`` resolves to the delta plan id, so the published identity
    is derived rather than supplied.

    A pre-computed ``preflight`` is accepted so a caller that already reduced the
    cohort against the base does not pay for the same read twice, and so the
    decision to fetch is made in exactly one place.

    ``progress`` carries the ``run`` and ``merge`` event shapes -- per-CIK fetch
    events then merge stage events -- because an augmentation does the longest
    silent work in the pipeline otherwise; the delta plan is announced as a
    ``delta_plan`` event because its size is not knowable before this call.
    """
    emit = _safe_progress(progress)
    check = preflight or preflight_augment(
        roster_from_manifest(manifest),
        metadata_paths,
        base_snapshot_id=base_snapshot_id,
    )
    base_parts = read_snapshot_parts(metadata_paths.snapshot_manifest(base_snapshot_id))
    base = check.base
    base_rows = (
        sum(int(part["row_count"]) for part in base_parts.layout.manifest["parts"])
        if base_parts.layout.multipart
        else base_parts.row_count
    )
    if check.is_empty:
        # Nothing to fetch is a result, not a failure: the base already holds the
        # request, so no client call is made, no delta plan is written, and no
        # snapshot or pointer is published.
        return AugmentResult(
            base_snapshot_id=base_snapshot_id,
            new_snapshot_id="",
            base_row_count=base_rows,
            delta_row_count=0,
            refetched_ciks=(),
            report=None,
            no_op=True,
            requested_cik_count=check.requested_count,
            already_present_count=check.already_present_count,
        )

    plan = derive_delta_plan(
        check.requested,
        check.base,
        chunk_size=chunk_size,
        base_snapshot_id=base_snapshot_id,
        input_name=manifest.input_name,
        input_fingerprint=manifest.input_fingerprint,
    )
    resolved_snapshot_id = new_snapshot_id or plan.plan_id
    run_paths = resolve_run_paths(plan.plan_id, metadata_paths.artifacts_root)
    write_plan(plan, run_paths)

    # Announced rather than pre-known: the delta size depends on which CIKs the
    # base already holds, so a caller cannot size a bar for the fetch the way
    # ``cmd_run`` does. It gets the plan here and sizes from this event.
    emit({"type": "delta_plan", "plan_id": plan.plan_id, "row_count": plan.row_count})
    results = run_chunk_ids(
        client,
        plan,
        run_paths,
        plan.chunk_ids(),
        snapshot_id=resolved_snapshot_id,
        workers=workers,
        progress=emit,
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
        emit({"type": "merge_stage", "stage": "validating"})
        if find_null_keys(con, inputs, "cik"):
            raise MergeError("augmentation rejected: null CIK in merged inputs")
        duplicates = find_duplicate_keys(con, inputs, "cik")
        if duplicates:
            raise MergeError(
                f"augmentation rejected: CIKs appear in both base and delta: "
                f"{duplicates}"
            )
        report.duplicate_accessions = find_duplicate_accessions(con, inputs)
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
    emit({"type": "merge_stage", "stage": "publishing_parts"})
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
    emit({"type": "readback_done", "rows": row_count})

    return AugmentResult(
        base_snapshot_id=base_snapshot_id,
        new_snapshot_id=resolved_snapshot_id,
        base_row_count=base_rows,
        delta_row_count=plan.row_count,
        refetched_ciks=tuple(refetched),
        report=report,
        no_op=False,
        requested_cik_count=check.requested_count,
        already_present_count=check.already_present_count,
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
