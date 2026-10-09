"""The one typed options model shared by the CLI and the interactive operator.

Executing a plan takes a plan reference, so a bundle worker needs no cohort.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.foundation.runtime.partitions import parse_id_selection
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.pipelines.cohort.operations import sample_cohort
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths

from .paths import (
    ASSIGNMENTS_DIR_NAME,
    CHUNKS_DIR_NAME,
    RECEIPT_FILE_NAME,
    ROSTER_DIR_NAME,
    MetadataPaths,
    resolve_metadata_paths,
    resolve_run_paths,
)
from .planner import Plan
from .roster import ROSTER_FILE_NAME, Roster, cohort_record_to_roster, read_roster

__all__ = [
    "BundleRunPaths",
    "PlanOptions",
    "RunOptions",
    "derive_plan_id",
    "plan_options",
    "read_bundle_plan_id",
    "resolve_chunk_size",
    "resolve_cohort",
    "run_options",
]


@dataclass(frozen=True, slots=True)
class BundleRunPaths:
    """Plan-scoped paths rooted at a copied bundle rather than an artifacts tree."""

    bundle_root: Path
    plan_id: str

    @property
    def plan_file(self) -> Path:
        """Execution manifest inside the copied bundle."""
        return self.bundle_root / PLAN_FILE_NAME

    @property
    def plan_bundle(self) -> Path:
        """Root of the copied bundle."""
        return self.bundle_root

    @property
    def roster_file(self) -> Path:
        """The CIK cohort inside the copied bundle."""
        return self.bundle_root / ROSTER_DIR_NAME / ROSTER_FILE_NAME

    @property
    def assignments_dir(self) -> Path:
        """Assignment directory inside the copied bundle."""
        return self.bundle_root / ASSIGNMENTS_DIR_NAME

    def assignment_file(self, assignment_id: str) -> Path:
        """Path of one assignment inside the copied bundle."""
        return self.assignments_dir / f"{assignment_id}.parquet"

    @property
    def chunk_dir(self) -> Path:
        """Local checkpoint directory for this worker's chunk files."""
        return self.bundle_root / CHUNKS_DIR_NAME

    def chunk_file(self, chunk_id: int) -> Path:
        """Checkpoint path for one chunk inside the copied bundle."""
        return self.chunk_dir / f"chunk_{chunk_id:04d}.parquet"

    @property
    def receipt_file(self) -> Path:
        """At the bundle root, so the returned directory reads as one thing."""
        return self.bundle_root / RECEIPT_FILE_NAME


def resolve_chunk_size(value: int | None) -> int:
    """Resolve the effective chunk size from an override or the settings registry."""
    if value is not None:
        return value
    return resolve_runtime_settings().default_chunk_size


@dataclass(slots=True)
class PlanOptions:
    """Everything that defines a plan; worker count must never reach plan identity."""

    cohort: str = ""
    artifacts_root: Path | None = None
    chunk_size: int = DEFAULT_CHUNK_SIZE
    limit: int | None = None

    def metadata(self) -> MetadataPaths:
        """Metadata layout this invocation writes into."""
        return resolve_metadata_paths(self.artifacts_root)

    def roster(self) -> Roster:
        """Resolve the selected cohort this invocation plans over."""
        return resolve_cohort(self).roster

    def selected_cohort(self) -> SelectedCohort:
        """Resolve the selected published cohort and its verified dataset."""
        return resolve_cohort(self)


@dataclass(frozen=True, slots=True)
class SelectedCohort:
    """A published cohort dataset adapted to the metadata roster contract."""

    roster: Roster
    input_name: str = ""
    input_fingerprint: str = ""


def resolve_cohort(options: PlanOptions) -> SelectedCohort:
    """Resolve the cohort named by these options, applying any selection limit."""
    if not options.cohort:
        raise ValueError("--cohort is required")
    if options.limit is not None and options.limit < 1:
        raise ValueError(f"--limit must be >= 1, got {options.limit}")
    paths = resolve_cohort_paths(options.metadata().artifacts_root)
    catalog = CohortCatalog(paths)
    record = catalog.resolve_cohort_identifier(options.cohort)
    roster = cohort_record_to_roster(record, paths)
    if options.limit is not None and options.limit < roster.row_count:
        if roster.dataset is None:
            raise ValueError("selected cohort has no dataset")
        output = (
            options.metadata().transient_dir(
                f"cohort-limit-{record.cohort_id}-{options.limit}"
            )
            / "ciks.parquet"
        )
        written = sample_cohort(roster.dataset, output, sample_limit=options.limit)
        roster = read_roster(output)
        if written != options.limit or roster.row_count != options.limit:
            raise ValueError("limited cohort has an unexpected row count")
    return SelectedCohort(
        roster=roster,
        input_name=f"cohort:{record.cohort_id}",
        input_fingerprint=record.dataset_sha256,
    )


@dataclass(slots=True)
class RunOptions:
    """Everything needed to execute a plan that already exists; ``plan_id`` is an
    input, so a bundle worker need not re-declare the chunking.
    """

    plan_id: str
    artifacts_root: Path | None = None
    bundle_root: Path | None = None
    worker_id: str = ""
    chunk_ids: tuple[int, ...] = ()
    workers: int | None = None
    snapshot_id: str = ""
    branch_name: str = "main"
    expected_branch_tip: str | None = None

    def run_paths(self) -> Any:
        """Plan-scoped paths; with ``bundle_root`` they point at a copied bundle."""
        if self.bundle_root is not None:
            return BundleRunPaths(bundle_root=self.bundle_root, plan_id=self.plan_id)
        return resolve_run_paths(self.plan_id, self.artifacts_root)

    def effective_snapshot_id(self, plan: Plan) -> str:
        """Snapshot identity for this run, plan-derived for a full ingest so a row's
        ``snapshot_id`` cannot disagree with the artifact holding it.
        """
        return self.snapshot_id or plan.plan_id


def plan_options(
    *,
    cohort: str = "",
    artifacts_root: str | Path | None = None,
    chunk_size: int | None = None,
    limit: int | None = None,
) -> PlanOptions:
    """Build plan options from raw values, resolving effective settings once."""
    return PlanOptions(
        cohort=cohort,
        artifacts_root=(Path(artifacts_root).resolve() if artifacts_root else None),
        chunk_size=resolve_chunk_size(chunk_size),
        limit=limit,
    )


def read_bundle_plan_id(bundle_root: Path | str) -> str:
    """Read the plan identity a copied bundle declares for itself."""
    manifest = Path(bundle_root) / PLAN_FILE_NAME
    if not manifest.is_file():
        return ""
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("plan_id", ""))
    except json.JSONDecodeError:
        return ""


def run_options(
    *,
    plan_id: str = "",
    cohort: str = "",
    chunk_size: int | None = None,
    limit: int | None = None,
    artifacts_root: str | Path | None = None,
    bundle_root: str | Path | None = None,
    worker_id: str = "",
    chunk_ids: list[int] | tuple[int, ...] | str = (),
    workers: int | None = None,
    snapshot_id: str = "",
    branch_name: str = "main",
    expected_branch_tip: str | None = None,
) -> RunOptions:
    """A plan reference arrives directly, from the cohort, or from a bundle
    naming itself.
    """
    if isinstance(chunk_ids, str):
        chunk_ids = parse_id_selection(chunk_ids) if chunk_ids else ()
    if bundle_root and not plan_id:
        plan_id = read_bundle_plan_id(bundle_root)
    if not plan_id and cohort:
        plan_id = derive_plan_id(
            plan_options(
                cohort=cohort,
                artifacts_root=artifacts_root,
                chunk_size=chunk_size,
                limit=limit,
            )
        )
    if not plan_id:
        raise ValueError(
            "a plan reference is required: --plan-id, --bundle, or --cohort"
        )
    return RunOptions(
        plan_id=plan_id,
        artifacts_root=(Path(artifacts_root).resolve() if artifacts_root else None),
        bundle_root=Path(bundle_root).resolve() if bundle_root else None,
        worker_id=worker_id,
        chunk_ids=tuple(int(chunk_id) for chunk_id in chunk_ids),
        workers=workers,
        snapshot_id=snapshot_id,
        branch_name=branch_name,
        expected_branch_tip=expected_branch_tip,
    )


def derive_plan_id(options: PlanOptions) -> str:
    """Deriving rather than recording is what makes planning idempotent."""
    from .planner import build_plan

    return build_plan(
        resolve_cohort(options).roster,
        chunk_size=options.chunk_size,
    ).plan_id
