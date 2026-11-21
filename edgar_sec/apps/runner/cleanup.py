"""Artifact lifecycle cleanup engine for transient runs and plan bundles."""

from __future__ import annotations

import shutil
from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    PLANS_DIR,
    TRANSIENT_DIR,
    resolve_paths,
)


def clear_transient(
    artifacts_root: Path | str | None = None,
    dataset: str | None = None,
    run_id: str | None = None,
) -> int:
    """Clear transient run staging directories across datasets or for a run."""
    root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    transient_base = root / TRANSIENT_DIR
    if not transient_base.is_dir():
        return 0

    cleared = 0
    if dataset is not None:
        ds_dir = transient_base / dataset
        if ds_dir.is_dir():
            if run_id is not None:
                target = ds_dir / run_id
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                    cleared += 1
            else:
                for child in list(ds_dir.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                        cleared += 1
    else:
        for ds_dir in list(transient_base.iterdir()):
            if not ds_dir.is_dir():
                continue
            if run_id is not None:
                target = ds_dir / run_id
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                    cleared += 1
            else:
                for child in list(ds_dir.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                        cleared += 1
    return cleared


def clear_plans(
    artifacts_root: Path | str | None = None,
    dataset: str | None = None,
    plan_id: str | None = None,
) -> int:
    """Clear planning directories for a dataset, specific plan, or all plans."""
    root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    if not root.is_dir():
        return 0

    cleared = 0
    candidate_dirs: list[Path] = []
    if dataset is not None:
        plans_dir = root / dataset / PLANS_DIR
        if plans_dir.is_dir():
            candidate_dirs.append(plans_dir)
    else:
        for child in list(root.iterdir()):
            if child.is_dir():
                plans_dir = child / PLANS_DIR
                if plans_dir.is_dir():
                    candidate_dirs.append(plans_dir)

    for plans_dir in candidate_dirs:
        if plan_id is not None:
            target = plans_dir / plan_id
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                cleared += 1
        else:
            for child in list(plans_dir.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                    cleared += 1
    return cleared


def prune_all_ephemeral(
    artifacts_root: Path | str | None = None,
) -> dict[str, int]:
    """Prune all transient execution and planning artifacts across workspace."""
    return {
        "transient": clear_transient(artifacts_root),
        "plans": clear_plans(artifacts_root),
    }


__all__ = [
    "clear_plans",
    "clear_transient",
    "prune_all_ephemeral",
]
