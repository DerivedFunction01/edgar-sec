"""Atomically publish immutable target-plan bundles."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_planning.discovery import (
    DocumentPlanError,
    PublishedDocumentPlan,
    read_published_plan,
    validate_staged_plan,
)
from edgar_sec.pipelines.document_planning.paths import DocumentPlanningPaths


@dataclass(frozen=True, slots=True)
class PublishedBundle:
    plan_id: str
    root: Path
    manifest: Mapping[str, Any]
    reused: bool


def reuse_plan_if_identical(
    plan_id: str,
    identity: Mapping[str, Any],
    expected_manifest: Mapping[str, Any] | None,
    paths: DocumentPlanningPaths,
) -> PublishedDocumentPlan | None:
    root = paths.plan_dir(plan_id)
    if not root.exists() and not root.is_symlink():
        return None
    try:
        existing = read_published_plan(plan_id, paths)
    except (OSError, ValueError) as error:
        raise DocumentPlanError(
            f"existing plan bundle is corrupt and will not be replaced: {plan_id}"
        ) from error
    if existing.manifest.get("plan_identity") != identity:
        raise DocumentPlanError("existing plan identity diverges")
    if expected_manifest is not None and existing.manifest != expected_manifest:
        raise DocumentPlanError("existing plan payload or part digests diverge")
    return existing


def publish_plan_bundle(
    plan_id: str,
    identity: Mapping[str, Any],
    manifest: Mapping[str, Any],
    staging_root: Path,
    paths: DocumentPlanningPaths,
) -> PublishedBundle:
    final_root = paths.plan_dir(plan_id)
    paths.plans_root.mkdir(parents=True, exist_ok=True)
    payload = dict(manifest)
    payload["plan_digest"] = canonical_hash(payload)
    atomic_write_json(staging_root / "plan.json", payload)
    validate_staged_plan(plan_id, staging_root)
    existing = reuse_plan_if_identical(plan_id, identity, payload, paths)
    if existing is not None:
        return PublishedBundle(plan_id, existing.root, existing.manifest, True)
    try:
        os.replace(staging_root, final_root)
    except OSError:
        existing = reuse_plan_if_identical(plan_id, identity, payload, paths)
        if existing is None:
            raise
        return PublishedBundle(plan_id, existing.root, existing.manifest, True)
    _fsync_directory(paths.plans_root)
    published = read_published_plan(plan_id, paths)
    if published.manifest != payload:
        raise DocumentPlanError(
            "published plan differs from the validated staging bundle"
        )
    return PublishedBundle(plan_id, final_root, published.manifest, False)


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["PublishedBundle", "publish_plan_bundle", "reuse_plan_if_identical"]
