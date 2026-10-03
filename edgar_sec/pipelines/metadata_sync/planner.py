"""Deterministic chunk planning over an immutable CIK roster.

A plan says *what* will be fetched and nothing about *who* fetches it. The
selected roster is stored once, as a content-addressed Parquet dataset beside a
small JSON manifest, so a plan document does not grow with the cohort. Chunk
membership is a range over roster ordinals, which is what makes that possible.

Identity is derived from the roster and the chunk layout, never from assignment,
worker count, or time. An assignment is a separate artifact, so moving work to a
different machine is not a different plan, and completed chunks survive it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.domain.submissions.schemas import SCHEMA_VERSION
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.infra.storage.atomic import atomic_write_json

from .manifest import InputManifest
from .paths import RunPaths
from .roster import Roster, RosterError, read_roster, roster_from_manifest, write_roster

PLAN_FORMAT_VERSION = "2.0.0"
PLAN_MANIFEST_KIND = "metadata_plan"

__all__ = [
    "PLAN_FORMAT_VERSION",
    "PLAN_MANIFEST_KIND",
    "Plan",
    "build_plan",
    "derive_plan_id",
    "load_plan",
    "utc_now_iso",
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
) -> str:
    """Derive a stable plan identifier from the plan-defining inputs.

    Assignment, worker count, and timestamps are excluded by construction: they
    are operational choices, and covering them is what would make reassigning a
    cohort discard its checkpoints. ``parent_id`` is the base snapshot for a delta
    plan, so the same requested CIK list against two different bases resolves to
    two different plans.
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
        )
    )
    return sha256_bytes(material.encode("utf-8"))[:16]


@dataclass(frozen=True, slots=True)
class Plan:
    """An immutable fetch plan: a cohort, a chunk layout, and a lineage.

    The roster is carried in memory because every consumer needs its own slice of
    it; it is loaded from the bundle rather than inlined, which is the whole
    point of the format. Chunks are ranges, so membership is arithmetic.
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
    registry_id: str = ""

    @property
    def row_count(self) -> int:
        """Number of CIKs this plan covers."""
        return self.roster.row_count

    def lineage(self) -> dict[str, str]:
        """Source identities carried from the cohort reference to publication.

        A plan built over a published registry roster records that registry, so
        the merged snapshot says which curated-versus-source projection the
        published rows came from instead of only naming a file.
        """
        recorded = {"registry_id": self.registry_id}
        if self.parent_id:
            recorded["parent_snapshot_id"] = self.parent_id
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

        Constant in the cohort size: chunk boundaries are ordinal ranges, and the
        cohort itself lives in the roster dataset this manifest references.
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
            "registry_id": self.registry_id,
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
    registry_id: str = "",
) -> Plan:
    """Build the immutable plan for a selected roster."""
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    if roster.is_empty:
        raise RosterError("a plan requires a non-empty roster")
    return Plan(
        plan_id=derive_plan_id(
            roster.roster_id, chunk_size, kind=kind, parent_id=parent_id
        ),
        roster=roster,
        chunk_size=chunk_size,
        kind=kind,
        parent_id=parent_id,
        created_at=created_at or utc_now_iso(),
        input_name=input_name,
        input_fingerprint=input_fingerprint,
        selected_limit=selected_limit,
        registry_id=registry_id,
    )


def plan_for_manifest(
    manifest: InputManifest,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    limit: int | None = None,
    kind: str = "full",
    parent_id: str = "",
    created_at: str | None = None,
) -> Plan:
    """Build a plan from a parsed manifest, applying a selection limit.

    The limit is applied to the roster *before* identity is derived, so a bounded
    plan and a full plan over the same file are different plans. Deriving identity
    from the raw file digest instead let the two collide on one plan directory.
    """
    from dataclasses import replace as _replace

    if limit is not None:
        if limit < 1:
            raise ValueError(f"--limit must be >= 1, got {limit}")
        selected = _replace(
            manifest, ciks=manifest.ciks[:limit], names=manifest.names[:limit]
        )
    else:
        selected = manifest
    plan = build_plan(
        roster_from_manifest(selected),
        chunk_size=chunk_size,
        kind=kind,
        parent_id=parent_id,
        input_name=selected.input_name,
        input_fingerprint=selected.input_fingerprint,
        created_at=created_at,
        selected_limit=limit,
    )
    return plan


def write_plan(plan: Plan, run_paths: RunPaths) -> str:
    """Write the plan bundle: roster dataset, execution manifest, input manifest.

    The roster is written first and its digest recorded, so a manifest on disk
    can never reference a cohort that is not there beside it.
    """
    digest = write_roster(plan.roster, run_paths.roster_file)
    manifest = plan.to_manifest()
    manifest["roster_artifact_sha256"] = digest
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

    A plan whose recorded inputs do not reproduce its id, whose versions differ
    from the running build, or whose roster does not match the recorded identity
    is rejected rather than reused. A stale plan must never produce a mislabeled
    snapshot, and a plan whose cohort was swapped must never drive a fetch.
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
    expected = derive_plan_id(
        roster.roster_id,
        chunk_size,
        kind=kind,
        parent_id=parent_id,
        plan_format_version=str(manifest.get("plan_format_version", "")),
        schema_version=str(manifest.get("schema_version", "")),
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
        registry_id=str(manifest.get("registry_id", "")),
    )


def _check_version(manifest: dict, key: str, expected: str, path: Path) -> None:
    """Reject a plan whose recorded version the current code no longer honours."""
    recorded = manifest.get(key)
    if recorded != expected:
        raise ValueError(
            f"incompatible plan at {path}: {key} is {recorded!r}, this build "
            f"requires {expected!r}; regenerate the plan"
        )
