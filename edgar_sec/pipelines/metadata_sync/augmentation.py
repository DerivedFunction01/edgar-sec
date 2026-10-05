"""Delta augmentation against a published snapshot.
The base is never refetched. A delta plan is identified by its base snapshot and
its delta roster -- never the request file -- and the published identity derives
from that.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    find_duplicate_keys,
    find_null_keys,
)

from .manifest import compile_cik_cohort
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
from .roster import Roster, RosterError, read_roster
from .sec_client import SubmissionsClient
from .snapshot import read_snapshot_parts
from .validation import find_duplicate_accessions
from .worker import run_chunk_ids

__all__ = [
    "AugmentPreflight",
    "AugmentResult",
    "augment",
    "augment_from_input",
    "augment_from_roster",
    "base_cik_sources",
    "derive_delta_cohort",
    "derive_delta_plan",
    "preflight_augment",
]


@dataclass(frozen=True, slots=True)
class AugmentPreflight:
    """What an augmentation would do, decided before anything is fetched.
    Counts, not cohorts: building the difference is the work this avoids.
    """

    base_snapshot_id: str
    requested_count: int
    already_present_count: int
    delta_count: int

    @property
    def is_empty(self) -> bool:
        """True when the base already holds every requested CIK."""
        return self.delta_count == 0

    def describe(self) -> str:
        """One operator-facing line describing the pending work."""
        return (
            f"{self.requested_count:,} requested, "
            f"{self.already_present_count:,} already in base {self.base_snapshot_id}, "
            f"{self.delta_count:,} to fetch"
        )


@dataclass(frozen=True, slots=True)
class AugmentResult:
    """Outcome of one augmentation run.
    ``report`` is ``None`` for a no-op; branch on ``no_op``.
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


def base_cik_sources(
    metadata_paths: MetadataPaths, snapshot_id: str
) -> tuple[list[str], bool]:
    """The published artifacts that hold a snapshot's CIK set.
    An unreadable base is an error, never mistaken for an empty one.
    """
    index_path = metadata_paths.snapshot_cik_index(snapshot_id)
    if index_path.is_file():
        return [str(index_path)], False
    parts = read_snapshot_parts(metadata_paths.snapshot_manifest(snapshot_id))
    return [str(path) for path in parts.paths], True


#: Overlap counted, not materialized. Both paths and both column names are
#: bound, so nothing here composes SQL text from a value.
_CIK_OVERLAP_QUERY = """
SELECT
    count(*) FILTER (WHERE base.cik IS NULL) AS absent_rows,
    count(*) FILTER (WHERE base.cik IS NOT NULL) AS present_rows
FROM read_parquet(?) AS requested
LEFT JOIN read_parquet(?) AS base ON base.cik = requested.cik_padded
"""

#: Ordinals are renumbered from zero: an ordinal is a position *within* a cohort,
#: and chunk ranges start at zero, so keeping the requested cohort's numbering
#: would leave the delta addressed from wherever the removed rows happened to fall.
_CIK_ANTI_JOIN_QUERY = """
WITH kept AS (
    SELECT ordinal, cik_padded, name
    FROM read_parquet(?) AS requested
    WHERE NOT EXISTS (
        SELECT 1 FROM read_parquet(?) AS base WHERE base.cik = requested.cik_padded
    )
)
SELECT
    row_number() OVER (ORDER BY ordinal) - 1 AS ordinal,
    cik_padded,
    name
FROM kept
ORDER BY ordinal
"""


def preflight_augment(
    requested: Roster,
    metadata_paths: MetadataPaths,
    *,
    base_snapshot_id: str,
) -> AugmentPreflight:
    """Decide what an augmentation would fetch, reading only published artifacts.
    An already-satisfied request is reported as no work, not refused.
    """
    sources, _from_parts = base_cik_sources(metadata_paths, base_snapshot_id)
    if requested.dataset is None or not sources:
        return AugmentPreflight(base_snapshot_id, 0, 0, 0)

    con = connect()
    try:
        absent, present = con.execute(
            _CIK_OVERLAP_QUERY, [[str(requested.dataset)], _base_path_list(sources)]
        ).fetchone()
    finally:
        con.close()

    return AugmentPreflight(
        base_snapshot_id=base_snapshot_id,
        requested_count=requested.row_count,
        already_present_count=int(present or 0),
        delta_count=int(absent or 0),
    )


def _base_path_list(sources: list[str]) -> list[str] | str:
    """Bind a single source directly and several as a list."""
    return sources[0] if len(sources) == 1 else [str(path) for path in sources]


def derive_delta_cohort(
    requested: Roster,
    metadata_paths: MetadataPaths,
    *,
    base_snapshot_id: str,
    destination: str | Path,
) -> Roster:
    """Materialize the CIKs the base does not hold as their own cohort.
    Written as a cohort because it carries an identity the merge report records.
    """
    if requested.dataset is None:
        raise RosterError("cannot reduce an empty cohort")
    sources, _from_parts = base_cik_sources(metadata_paths, base_snapshot_id)
    con = connect()
    try:
        copy_query_to_parquet(
            con,
            _CIK_ANTI_JOIN_QUERY,
            destination,
            params=[[str(requested.dataset)], _base_path_list(sources)],
        )
    finally:
        con.close()
    return read_roster(destination)


def delta_cohort_path(
    requested: Roster, metadata_paths: MetadataPaths, base_snapshot_id: str
) -> Path:
    """Where the difference between a requested cohort and a base is compiled.

    Keyed by both inputs, so two different reductions never share a cohort.
    """
    key = f"{requested.roster_id}-minus-{base_snapshot_id}"
    return metadata_paths.compiled_cohort_file(key)


def derive_delta_plan(
    requested: Roster,
    metadata_paths: MetadataPaths,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    base_snapshot_id: str,
    input_name: str = "",
    input_fingerprint: str = "",
    created_at: str | None = None,
) -> Plan:
    """Build the plan covering exactly the CIKs absent from the base snapshot."""
    delta = derive_delta_cohort(
        requested,
        metadata_paths,
        base_snapshot_id=base_snapshot_id,
        destination=delta_cohort_path(requested, metadata_paths, base_snapshot_id),
    )
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


#: Symmetric difference between published and expected CIKs; zero is the only
#: acceptable answer, since counts alone would not prove the sets match.
_CIK_SET_DIFFERENCE_QUERY = """
WITH merged AS (SELECT DISTINCT cik FROM read_parquet(?)),
     carried AS (SELECT DISTINCT cik FROM read_parquet(?)),
     fetched AS (SELECT DISTINCT cik_padded AS cik FROM read_parquet(?)),
     expected AS (SELECT cik FROM carried UNION SELECT cik FROM fetched)
SELECT
    (SELECT count(*) FROM (SELECT cik FROM merged EXCEPT SELECT cik FROM expected))
    + (SELECT count(*) FROM (SELECT cik FROM expected EXCEPT SELECT cik FROM merged))
"""


def _ciks_outside_expected(
    metadata_paths: MetadataPaths,
    base_snapshot_id: str,
    delta: Roster,
    published_parts: list[str],
) -> int:
    """Count the CIKs by which a merged snapshot differs from base plus delta."""
    if delta.dataset is None:
        raise RosterError("cannot verify a merge against an empty delta")
    sources, _from_parts = base_cik_sources(metadata_paths, base_snapshot_id)
    con = connect()
    try:
        return int(
            con.execute(
                _CIK_SET_DIFFERENCE_QUERY,
                [
                    [str(path) for path in published_parts],
                    _base_path_list(sources),
                    str(delta.dataset),
                ],
            ).fetchone()[0]
        )
    finally:
        con.close()


def augment(
    client: SubmissionsClient,
    requested: Roster,
    metadata_paths: MetadataPaths,
    *,
    base_snapshot_id: str,
    new_snapshot_id: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    workers: int | None = None,
    lineage: dict[str, str] | None = None,
    preflight: AugmentPreflight | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    input_name: str = "",
    input_fingerprint: str = "",
) -> AugmentResult:
    """Augment a published snapshot with any newly requested CIKs.
    The base is carried forward and never refetched; its rows keep their original
    ``snapshot_id``, which is row provenance.
    """
    emit = _safe_progress(progress)
    check = preflight or preflight_augment(
        requested,
        metadata_paths,
        base_snapshot_id=base_snapshot_id,
    )
    base_parts = read_snapshot_parts(metadata_paths.snapshot_manifest(base_snapshot_id))
    base_rows = (
        sum(int(part["row_count"]) for part in base_parts.layout.manifest["parts"])
        if base_parts.layout.multipart
        else base_parts.row_count
    )
    if check.is_empty:
        # Nothing to fetch is a result, not a failure: no client call, no delta
        # plan, no snapshot or pointer published.
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
        requested,
        metadata_paths,
        chunk_size=chunk_size,
        base_snapshot_id=base_snapshot_id,
        input_name=input_name,
        input_fingerprint=input_fingerprint,
    )
    resolved_snapshot_id = new_snapshot_id or plan.plan_id
    run_paths = resolve_run_paths(plan.plan_id, metadata_paths.artifacts_root)
    write_plan(plan, run_paths)

    # Announced rather than pre-known: delta size depends on which CIKs the base
    # already holds, so a caller can only size its bar from this event.
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
    stray = _ciks_outside_expected(
        metadata_paths, base_snapshot_id, plan.roster, [str(p) for p in part_paths]
    )
    if stray:
        raise MergeError(
            "augmentation rejected: merged CIK set differs from base plus delta "
            f"by {stray} CIKs"
        )
    merged = _published_ciks(part_paths)

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
    """Augment from an already-resolved cohort rather than a CIK input file."""
    return augment(
        client,
        requested,
        metadata_paths,
        base_snapshot_id=base_snapshot_id,
        new_snapshot_id=new_snapshot_id,
        **kwargs,
    )


def augment_from_input(
    client: SubmissionsClient,
    input_path: str,
    metadata_paths: MetadataPaths,
    **kwargs: Any,
) -> AugmentResult:
    """Compile a CIK input file into a cohort and augment from it."""
    cohort = compile_cik_cohort(input_path, metadata_paths=metadata_paths)
    return augment(
        client,
        cohort.roster,
        metadata_paths,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
        **kwargs,
    )
