"""Immutable publication contract for Phase 02 target-plan bundles.

Published plans are immutable, selectable work orders: each bundle is built in
a transient staging directory beside its destination and renamed into place
only when complete, so a published plan is never partially visible. An exact
rerun reuses the published bundle; an incomplete or diverging directory is a
conflict that must be removed manually instead of being rewritten.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from defs.storage import load_json

SCOPE_DETERMINISTIC = "deterministic"
SCOPE_POLICY = "policy"

REQUIRED_PLAN_FILES = (
    "plan.json",
    "selection_report.json",
    "locator_groups.parquet",
)


def plan_bundle_complete(plan_dir: Path) -> bool:
    """Check that a plan bundle contains every required published artifact."""
    targets_dir = plan_dir / "targets"
    return (
        all((plan_dir / name).is_file() for name in REQUIRED_PLAN_FILES)
        and targets_dir.is_dir()
        and any(targets_dir.glob("form=*/data.parquet"))
    )


def reuse_existing_plan(
    final_dir: Path,
    plan_id: str,
    scope: str,
    *,
    expected_meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return an existing complete plan bundle, or raise on a conflicting one.

    ``expected_meta`` additionally pins request-derived fields (forms,
    amendment, limit, document suffixes) so hash-collision or manual edits
    surface as conflicts instead of silent reuse.
    """
    if not final_dir.is_dir():
        return None
    plan_meta = load_json(final_dir / "plan.json", default=None)
    if (
        not isinstance(plan_meta, dict)
        or str(plan_meta.get("plan_id") or plan_meta.get("run_id")) != plan_id
        or plan_meta.get("scope") != scope
        or not plan_bundle_complete(final_dir)
        or (
            expected_meta is not None
            and any(plan_meta.get(key) != value for key, value in expected_meta.items())
        )
    ):
        raise ValueError(
            f"existing target plan directory is incomplete or conflicts with "
            f"plan id {plan_id}: {final_dir}; remove it manually to regenerate"
        )
    if scope == SCOPE_POLICY:
        from .plan_expansion import plan_fingerprint, plan_locator_keys

        if plan_meta.get("plan_fingerprint") != plan_fingerprint(
            plan_meta, plan_locator_keys(final_dir)
        ):
            raise ValueError(
                f"existing target plan fingerprint mismatch: {final_dir}; "
                "remove it manually to regenerate"
            )
    return plan_meta


def publish_plan_bundle(staging_dir: Path, final_dir: Path) -> None:
    """Atomically move a fully built staging bundle into its published place."""
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging_dir, final_dir)


@contextmanager
def staged_plan_bundle(final_dir: Path, plan_id: str) -> Iterator[Path]:
    """Yield a transient staging bundle and publish it atomically on success.

    The staging directory is a sibling of the published bundle so the final
    rename stays on one filesystem. Any failure removes the staging directory.
    """
    staging_dir = final_dir.parent / f".staging-{plan_id}-{os.getpid()}"
    shutil.rmtree(staging_dir, ignore_errors=True)
    try:
        yield staging_dir
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    publish_plan_bundle(staging_dir, final_dir)


__all__ = [
    "REQUIRED_PLAN_FILES",
    "SCOPE_DETERMINISTIC",
    "SCOPE_POLICY",
    "plan_bundle_complete",
    "publish_plan_bundle",
    "reuse_existing_plan",
    "staged_plan_bundle",
]
