"""The one typed options model shared by the CLI and the interactive operator.

The role split is the point: executing a plan needs a plan reference, so a
worker holding only a copied bundle runs without the CSV that defined it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.partitions import parse_id_selection
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE

from .manifest import CompiledCohort, compile_cik_cohort
from .paths import (
    RECEIPT_FILE_NAME,
    MetadataPaths,
    resolve_metadata_paths,
    resolve_run_paths,
)
from .planner import Plan
from .registry import load_registry_roster
from .roster import Roster

__all__ = [
    "BundleRunPaths",
    "PlanOptions",
    "RunOptions",
    "augment_options",
    "derive_plan_id",
    "plan_options",
    "read_bundle_plan_id",
    "resolve_chunk_size",
    "resolve_cohort",
    "run_options",
]


@dataclass(frozen=True, slots=True)
class BundleRunPaths:
    """Plan-scoped paths rooted at a copied bundle rather than an artifacts tree.
    A bundle worker has no plan under ``metadata/plans/``.
    """

    bundle_root: Path
    plan_id: str

    @property
    def plan_file(self) -> Path:
        """Execution manifest inside the copied bundle."""
        return self.bundle_root / "plan.json"

    @property
    def plan_bundle(self) -> Path:
        """Root of the copied bundle."""
        return self.bundle_root

    @property
    def roster_file(self) -> Path:
        """The CIK cohort inside the copied bundle."""
        return self.bundle_root / "roster" / "ciks.parquet"

    @property
    def assignments_dir(self) -> Path:
        """Assignment directory inside the copied bundle."""
        return self.bundle_root / "assignments"

    def assignment_file(self, assignment_id: str) -> Path:
        """Path of one assignment inside the copied bundle."""
        return self.assignments_dir / f"{assignment_id}.parquet"

    @property
    def chunk_dir(self) -> Path:
        """Local checkpoint directory for this worker's chunk files."""
        return self.bundle_root / "chunks"

    def chunk_file(self, chunk_id: int) -> Path:
        """Checkpoint path for one chunk inside the copied bundle."""
        return self.chunk_dir / f"chunk_{chunk_id:04d}.parquet"

    @property
    def receipt_file(self) -> Path:
        """The worker's receipt, at the root of what it hands back.

        At the bundle root so the returned directory reads as one thing.
        """
        return self.bundle_root / RECEIPT_FILE_NAME


def resolve_chunk_size(value: int | None) -> int:
    """Resolve the effective chunk size from an override or the settings registry."""
    if value is not None:
        return value
    return resolve_runtime_settings().default_chunk_size


@dataclass(slots=True)
class PlanOptions:
    """Everything that defines a plan, and nothing operational.
    Worker count is deliberately not a field: it must never reach a plan identity.
    """

    input_path: Path | None = None
    registry_id: str = ""
    artifacts_root: Path | None = None
    chunk_size: int = DEFAULT_CHUNK_SIZE
    limit: int | None = None

    def metadata(self) -> MetadataPaths:
        """Metadata layout this invocation writes into."""
        return resolve_metadata_paths(self.artifacts_root)

    def roster(self) -> Roster:
        """Resolve the selected cohort this invocation plans over.
        A registry roster and a compiled CSV converge here.
        """
        if self.registry_id:
            if self.input_path is not None:
                raise ValueError("pass --input or --roster, not both")
            return load_registry_roster(self.registry_id, self.metadata())
        if self.input_path is None:
            raise ValueError("a plan needs --input or --roster")
        return self.selected_cohort().roster

    def selected_cohort(self) -> SelectedCohort:
        """The cohort this invocation selected, with its provenance intact.
        The limit applies during compilation, before identity is derived.
        """
        if self.input_path is None:
            raise ValueError("a plan needs --input or --roster")
        if self.limit is not None and self.limit < 1:
            raise ValueError(f"--limit must be >= 1, got {self.limit}")
        cohort = compile_cik_cohort(
            self.input_path, limit=self.limit, metadata_paths=self.metadata()
        )
        return SelectedCohort.from_compiled(cohort)

    def lineage(self) -> dict[str, str]:
        """Source identities to record on anything this plan publishes."""
        if not self.registry_id:
            return {"registry_id": ""}
        return {"registry_id": self.registry_id}


@dataclass(frozen=True, slots=True)
class SelectedCohort:
    """A resolved cohort plus where it came from.
    A registry roster has no input file, so its registry identity stands in for an
    input fingerprint.
    """

    roster: Roster
    input_name: str = ""
    input_fingerprint: str = ""

    @classmethod
    def from_compiled(cls, cohort: CompiledCohort) -> SelectedCohort:
        """Build from a cohort compiled out of a CIK input file.
        The limit is already in that identity; re-truncating would hide a mistake.
        """
        return cls(
            roster=cohort.roster,
            input_name=cohort.input_name,
            input_fingerprint=cohort.input_fingerprint,
        )

    @classmethod
    def from_registry(cls, registry_id: str, roster: Roster) -> SelectedCohort:
        """Build from a published registry roster, whose fingerprint is its id."""
        return cls(
            roster=roster,
            input_name=f"registry:{registry_id}",
            input_fingerprint=roster.roster_id,
        )


def resolve_cohort(options: PlanOptions) -> SelectedCohort:
    """Resolve the cohort named by these options, applying any selection limit."""
    if options.registry_id:
        return SelectedCohort.from_registry(
            options.registry_id,
            load_registry_roster(options.registry_id, options.metadata()),
        )
    return options.selected_cohort()


@dataclass(slots=True)
class RunOptions:
    """Everything needed to execute a plan that already exists.
    ``plan_id`` is an input, so a bundle worker need not re-declare the chunking.
    """

    plan_id: str
    artifacts_root: Path | None = None
    bundle_root: Path | None = None
    worker_id: str = ""
    chunk_ids: tuple[int, ...] = ()
    workers: int | None = None
    snapshot_id: str = ""

    def run_paths(self) -> Any:
        """Plan-scoped paths for this execution.

        With ``bundle_root`` the paths point at another machine's copied bundle.
        """
        if self.bundle_root is not None:
            return BundleRunPaths(bundle_root=self.bundle_root, plan_id=self.plan_id)
        return resolve_run_paths(self.plan_id, self.artifacts_root)

    def effective_snapshot_id(self, plan: Plan) -> str:
        """Snapshot identity for this run.
        Plan-derived for a full ingest, so a row's ``snapshot_id`` cannot disagree with
        the artifact holding it.
        """
        return self.snapshot_id or plan.plan_id


def plan_options(
    *,
    input_path: str | Path | None = None,
    registry_id: str = "",
    artifacts_root: str | Path | None = None,
    chunk_size: int | None = None,
    limit: int | None = None,
) -> PlanOptions:
    """Build plan options from raw values, resolving effective settings once."""
    return PlanOptions(
        input_path=Path(input_path).resolve() if input_path else None,
        registry_id=registry_id,
        artifacts_root=(Path(artifacts_root).resolve() if artifacts_root else None),
        chunk_size=resolve_chunk_size(chunk_size),
        limit=limit,
    )


def read_bundle_plan_id(bundle_root: Path | str) -> str:
    """Read the plan identity a copied bundle declares for itself.
    A separate marker file would be a second source of truth.
    """
    manifest = Path(bundle_root) / "plan.json"
    if not manifest.is_file():
        return ""
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("plan_id", ""))
    except json.JSONDecodeError:
        return ""


def run_options(
    *,
    plan_id: str = "",
    input_path: str | Path | None = None,
    registry_id: str = "",
    chunk_size: int | None = None,
    limit: int | None = None,
    artifacts_root: str | Path | None = None,
    bundle_root: str | Path | None = None,
    worker_id: str = "",
    chunk_ids: list[int] | tuple[int, ...] | str = (),
    workers: int | None = None,
    snapshot_id: str = "",
) -> RunOptions:
    """Build execution options from raw values, resolving chunk selections.
    A plan reference arrives directly, from the cohort, or from a bundle naming itself.
    """
    if isinstance(chunk_ids, str):
        chunk_ids = parse_id_selection(chunk_ids) if chunk_ids else ()
    if bundle_root and not plan_id:
        plan_id = read_bundle_plan_id(bundle_root)
    if not plan_id and (input_path or registry_id):
        plan_id = derive_plan_id(
            plan_options(
                input_path=input_path,
                registry_id=registry_id,
                artifacts_root=artifacts_root,
                chunk_size=chunk_size,
                limit=limit,
            )
        )
    if not plan_id:
        raise ValueError(
            "a plan reference is required: --plan-id, --bundle, --input, or --roster"
        )
    return RunOptions(
        plan_id=plan_id,
        artifacts_root=(Path(artifacts_root).resolve() if artifacts_root else None),
        bundle_root=Path(bundle_root).resolve() if bundle_root else None,
        worker_id=worker_id,
        chunk_ids=tuple(int(chunk_id) for chunk_id in chunk_ids),
        workers=workers,
        snapshot_id=snapshot_id,
    )


def derive_plan_id(options: PlanOptions) -> str:
    """Derive the plan id a cohort reference and chunk layout resolve to.
    Deriving rather than recording is what makes planning idempotent.
    """
    from .planner import build_plan

    return build_plan(
        resolve_cohort(options).roster,
        chunk_size=options.chunk_size,
    ).plan_id


def augment_options(
    *,
    input_path: str | Path | None = None,
    registry_id: str = "",
    artifacts_root: str | Path | None = None,
    chunk_size: int | None = None,
    base_snapshot_id: str = "",
    new_snapshot_id: str = "",
    workers: int | None = None,
) -> tuple[PlanOptions, dict[str, str]]:
    """Build the options and lineage an augmentation run needs.
    The base is explicit; the new snapshot id defaults to the derived delta plan id.
    """
    options = plan_options(
        input_path=input_path,
        registry_id=registry_id,
        artifacts_root=artifacts_root,
        chunk_size=chunk_size,
    )
    lineage = options.lineage()
    lineage["parent_snapshot_id"] = base_snapshot_id
    return options, lineage
