"""Repository and artifact paths owned by document planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from edgar_sec.foundation.runtime.paths import (
    PLAN_FILE_NAME,
    ProjectPaths,
    resolve_paths,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    form_partition_name,
    resolve_filing_catalog_paths,
    safe_identifier,
)
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths

PIPELINE_DIR = "document_planning"
PLANS_DIR_NAME = "plans"
POLICY_DIR_NAME = "policies"
PROFILES_DIR_NAME = "profiles"
_PROFILE_ID_RE = re.compile(r"[A-Za-z0-9_.-]+\Z", re.ASCII)


class CatalogPaths(Protocol):
    @property
    def plans_root(self) -> Path: ...

    def plan_dir(self, plan_id: str) -> Path: ...


def resolve_catalog_paths(
    artifacts_root: str | Path | None = None,
) -> CatalogPaths:
    return resolve_filing_catalog_paths(artifacts_root=artifacts_root)


def catalog_form_partition_name(form: str) -> str:
    return form_partition_name(form)


def validate_catalog_plan_id(plan_id: str) -> str:
    return safe_identifier(plan_id)


def resolve_inventory_paths(
    artifacts_root: str | Path | None = None,
) -> InventoryPaths:
    root = (
        Path(artifacts_root).resolve()
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    return InventoryPaths(root)


def validate_profile_id(profile_id: str) -> str:
    """Return a safe profile filename stem or raise ``ValueError``."""
    if (
        not isinstance(profile_id, str)
        or profile_id in {".", ".."}
        or not _PROFILE_ID_RE.fullmatch(profile_id)
    ):
        raise ValueError(f"invalid profile_id: {profile_id!r}")
    return profile_id


@dataclass(frozen=True, slots=True)
class DocumentPlanningPaths:
    """Resolved policy and plan locations for one workspace."""

    project: ProjectPaths

    @property
    def repo_root(self) -> Path:
        return self.project.repo_root

    @property
    def artifacts_root(self) -> Path:
        return self.project.artifacts_root

    @property
    def profiles_root(self) -> Path:
        return self.artifacts_root / PIPELINE_DIR / PROFILES_DIR_NAME

    @property
    def plans_root(self) -> Path:
        return self.artifacts_root / PIPELINE_DIR / PLANS_DIR_NAME

    def profile_path(self, profile_id: str) -> Path:
        return self.profiles_root / f"{validate_profile_id(profile_id)}.json"

    def plan_dir(self, plan_id: str) -> Path:
        return self.plans_root / _validate_plan_id(plan_id)

    def plan_manifest_path(self, plan_id: str) -> Path:
        return self.plan_dir(plan_id) / PLAN_FILE_NAME


def _validate_plan_id(plan_id: str) -> str:
    if (
        not isinstance(plan_id, str)
        or plan_id in {".", ".."}
        or not _PROFILE_ID_RE.fullmatch(plan_id)
    ):
        raise ValueError(f"invalid plan_id: {plan_id!r}")
    return plan_id


def resolve_document_planning_paths(
    repo_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
) -> DocumentPlanningPaths:
    """Resolve policy paths from the repository and artifacts from settings."""
    root = Path(repo_root).resolve() if repo_root is not None else None
    project = resolve_paths(root)
    if artifacts_root is not None:
        project = ProjectPaths(
            repo_root=project.repo_root,
            artifacts_root=Path(artifacts_root).resolve(),
            uploads_root=project.uploads_root,
        )
    return DocumentPlanningPaths(project)


__all__ = [
    "PROFILES_DIR_NAME",
    "CatalogPaths",
    "DocumentPlanningPaths",
    "PIPELINE_DIR",
    "PLANS_DIR_NAME",
    "POLICY_DIR_NAME",
    "resolve_document_planning_paths",
    "resolve_inventory_paths",
    "resolve_catalog_paths",
    "catalog_form_partition_name",
    "validate_catalog_plan_id",
    "validate_profile_id",
]
