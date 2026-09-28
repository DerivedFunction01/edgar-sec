"""Immutable publication contract for target-plan bundles.

A published plan is a selectable work order. Each bundle is assembled in a
staging directory that is a *sibling* of its destination, so the final
``os.replace`` stays on one filesystem and is therefore atomic. A published
bundle is never partially visible.

Reuse policy: an exact rerun reuses the published bundle; an incomplete or
diverging directory is a conflict that must be removed deliberately rather than
being rewritten in place.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.filing_catalog.paths import (
    PLAN_FILE_NAME,
    PLAN_TARGETS_DIR_NAME,
    REQUIRED_PLAN_FILES,
    SELECTION_REPORT_NAME,
    form_partition_name,
)

# Bump when the plan document or selection report changes shape.
TARGET_PLAN_SCHEMA_VERSION = "1.0"


class PlanConflictError(RuntimeError):
    """A published plan directory exists but does not match the request."""


def plan_identity(payload: dict[str, Any]) -> str:
    """Derive a content-addressed plan id from the request that defines it.

    The same catalog and the same filters always yield the same id, so an exact
    rerun resolves to the same published bundle instead of forking a new one.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def plan_bundle_complete(plan_dir: Path) -> bool:
    """Report whether a plan bundle holds every required published artifact.

    Completeness is checked against the plan's own recorded counts rather than
    by asking whether any partition exists. v1 used ``any(glob('form=*/data.parquet'))``,
    which reports a legitimately empty plan (every filter excluded everything) as
    incomplete and therefore unreusable. Matching the on-disk partition set
    against ``plan.json`` also catches a bundle that lost a shard.
    """
    if not all((plan_dir / name).is_file() for name in REQUIRED_PLAN_FILES):
        return False
    targets_dir = plan_dir / PLAN_TARGETS_DIR_NAME
    if not targets_dir.is_dir():
        return False
    published = _load_plan_json(plan_dir)
    if published is None:
        return False
    counts = published.get("counts")
    if not isinstance(counts, dict):
        return False
    expected = {f"form={form_partition_name(form)}" for form in counts}
    present = {
        entry.name
        for entry in targets_dir.glob("form=*")
        if entry.is_dir() and (entry / "data.parquet").is_file()
    }
    return present == expected


def _load_plan_json(plan_dir: Path) -> dict[str, Any] | None:
    path = plan_dir / PLAN_FILE_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def reuse_existing_plan(
    final_dir: Path,
    plan_id: str,
    scope: str,
    *,
    expected_meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a published bundle when it already satisfies the request.

    Returns ``None`` when nothing is published yet. Raises
    :class:`PlanConflictError` when a directory exists but is incomplete or
    describes a different request, because silently rewriting it would destroy
    an immutable published artifact.
    """
    if not final_dir.exists():
        return None

    if not plan_bundle_complete(final_dir):
        raise PlanConflictError(
            f"incomplete plan bundle at {final_dir}; remove it and rerun to republish"
        )

    published = _load_plan_json(final_dir)
    if published is None:
        raise PlanConflictError(f"plan bundle at {final_dir} has no readable plan.json")

    if published.get("plan_id") != plan_id or published.get("scope") != scope:
        raise PlanConflictError(
            f"plan bundle at {final_dir} describes a different request; remove "
            "it or publish under a different plan id"
        )

    if expected_meta:
        mismatched = {
            key: (expected_meta[key], published.get(key))
            for key in expected_meta
            if published.get(key) != expected_meta[key]
        }
        if mismatched:
            raise PlanConflictError(
                f"plan bundle at {final_dir} diverges from the current request: "
                f"{sorted(mismatched)}"
            )

    return published


def publish_plan_bundle(staging_dir: Path, final_dir: Path) -> None:
    """Move a fully built staging bundle into its published location.

    ``os.replace`` is atomic only within a filesystem, which is why the staging
    directory is created as a sibling of ``final_dir``.
    """
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging_dir, final_dir)


@contextmanager
def staged_plan_bundle(final_dir: Path, plan_id: str) -> Iterator[Path]:
    """Yield a sibling staging directory and publish it atomically on success.

    On any failure the staging directory is removed, so a partial bundle is
    never left where a later run could mistake it for published state.
    """
    staging_dir = final_dir.parent / f".{final_dir.name}.staging.{plan_id}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield staging_dir
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    else:
        if final_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise PlanConflictError(
                f"plan bundle appeared at {final_dir} during publication"
            )
        publish_plan_bundle(staging_dir, final_dir)


def write_plan_documents(
    staging_dir: Path,
    plan_meta: dict[str, Any],
    selection_report: dict[str, Any],
) -> None:
    """Write the two required JSON documents of a plan bundle."""
    atomic_write_json(staging_dir / PLAN_FILE_NAME, plan_meta, indent=2)
    atomic_write_json(staging_dir / SELECTION_REPORT_NAME, selection_report, indent=2)


__all__ = [
    "REQUIRED_PLAN_FILES",
    "TARGET_PLAN_SCHEMA_VERSION",
    "PlanConflictError",
    "plan_bundle_complete",
    "plan_identity",
    "publish_plan_bundle",
    "reuse_existing_plan",
    "staged_plan_bundle",
    "write_plan_documents",
]
