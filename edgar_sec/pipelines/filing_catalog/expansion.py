"""Parent-plan validation and immutable target-plan expansion.
The invariant is strict: **the child contains 100% of the parent's locators**, since
a quiet resample makes a downstream acquisition skip committed documents. It holds
because the child's selection excludes the parent's keys before any pool is drawn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.filters import normalize_suffixes
from edgar_sec.engine.selection.policy import (
    SelectionPolicy,
    compute_seed_fingerprint,
    read_seed_filers_csv,
)
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.pipelines.filing_catalog.paths import (
    EXPANSION_METADATA_FILE,
    FilingCatalogPaths,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planner import SCOPE_POLICY, plan_policy
from edgar_sec.pipelines.filing_catalog.publication import (
    TARGET_PLAN_SCHEMA_VERSION,
    plan_fingerprint,
    plan_locator_keys,
)

# Fields that legitimately differ between a parent and its child.
_CHILD_ONLY_FIELDS = (
    "base_content_units",
    "level",
    "parent_plan_id",
    "parent_plan_fingerprint",
)

# Fields every current-schema policy plan carries
_REQUIRED_PARENT_FIELDS = (
    "plan_id",
    "catalog_id",
    "policy_corpus",
    "seed_fingerprint",
    "plan_fingerprint",
)


class ParentPlanError(ValueError):
    """A plan cannot be expanded from the requested parent."""


@dataclass(frozen=True, slots=True)
class ExpansionLineage:
    """What a child plan records about where it came from."""

    parent_plan_id: str
    parent_plan_fingerprint: str
    target_units: int
    parent_locator_count: int
    child_locator_count: int

    @property
    def added_locator_count(self) -> int:
        return self.child_locator_count - self.parent_locator_count

    @property
    def expansion_ratio(self) -> float:
        """Child size as a multiple of the parent, rounded for readability."""
        if self.parent_locator_count == 0:
            return 0.0
        return round(self.child_locator_count / self.parent_locator_count, 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_plan_id": self.parent_plan_id,
            "parent_plan_fingerprint": self.parent_plan_fingerprint,
            "target_units": self.target_units,
            "parent_locator_count": self.parent_locator_count,
            "child_locator_count": self.child_locator_count,
            "retained_locator_count": self.parent_locator_count,
            "added_locator_count": self.added_locator_count,
            "expansion_ratio": self.expansion_ratio,
        }


def _read_plan_json(plan_dir: Path) -> dict[str, Any]:
    path = plan_dir / PLAN_FILE_NAME
    if not path.is_file():
        raise ParentPlanError(f"parent plan has no {PLAN_FILE_NAME}: {plan_dir}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ParentPlanError(f"parent plan.json is unreadable: {plan_dir}") from error


def _read_parent_seed_filers(
    paths: FilingCatalogPaths, plan_id: str, parent_root: Path
) -> dict[str, Any]:
    """Load a parent plan's published seed sidecar, or why it cannot be.

    A bare ``FileNotFoundError`` misleads: the operator did not mis-type a path.
    """
    sidecar = paths.plan_seed_filers(plan_id)
    try:
        return read_seed_filers_csv(sidecar)
    except (FileNotFoundError, ValueError) as error:
        raise ParentPlanError(
            f"parent plan seed sidecar is unusable ({error}); the bundle at "
            f"{parent_root} is incomplete and must be republished"
        ) from error


def _inherited_policy_fields(policy: SelectionPolicy) -> dict[str, Any]:
    """The policy fields a child must inherit unchanged from its parent."""
    data = policy.to_dict()
    for field_name in _CHILD_ONLY_FIELDS:
        data.pop(field_name, None)
    return data


def validate_parent_schema(parent_meta: dict[str, Any]) -> None:
    """Reject a parent plan this build cannot expand from.
    An explicit directory gets no protection from plan identity, and nothing stops
    ``--parent`` pointing at an older-schema bundle. Republish it.
    """
    version = parent_meta.get("plan_schema_version")
    if version != TARGET_PLAN_SCHEMA_VERSION:
        raise ParentPlanError(
            f"parent plan schema is {version!r}, this build expands "
            f"{TARGET_PLAN_SCHEMA_VERSION!r} plans only; republish the parent plan"
        )
    missing = [
        name
        for name in _REQUIRED_PARENT_FIELDS
        if not str(parent_meta.get(name) or "").strip()
    ]
    if missing:
        raise ParentPlanError(
            f"parent plan is missing required {TARGET_PLAN_SCHEMA_VERSION} fields "
            f"{missing}: republish the parent plan"
        )


def validate_parent(
    parent_meta: dict[str, Any],
    parent_policy: SelectionPolicy | None,
    policy: SelectionPolicy,
    catalog_id: str,
    seed_fingerprint: str,
) -> SelectionPolicy | None:
    """Reject a child policy that does not extend its parent.
    Returns the parent's *resolved* policy when embedded, so the child derives from the
    constraints the parent was built under.
    """
    if parent_meta.get("scope") != SCOPE_POLICY:
        raise ParentPlanError("plan expansion requires a policy-driven parent plan")
    if str(parent_meta.get("catalog_id")) != catalog_id:
        raise ParentPlanError("parent and child plans must use the same catalog")
    if parent_meta["policy_corpus"] != policy.corpus_id:
        raise ParentPlanError("parent and child plans must use the same policy corpus")
    if parent_meta["seed_fingerprint"] != seed_fingerprint:
        raise ParentPlanError("parent and child plans must use the same seed CIK set")

    parent_forms = {str(form).upper() for form in parent_meta.get("forms") or []}
    child_forms = {str(form).upper() for form in policy.forms}
    if parent_forms and parent_forms != child_forms:
        raise ParentPlanError("parent and child plans must use the same forms")

    if parent_policy is None:
        embedded = parent_meta.get("selection_policy")
        if isinstance(embedded, dict):
            parent_policy = SelectionPolicy.from_dict(embedded)
    if parent_policy is not None and not _inherits_resolution(parent_policy, policy):
        raise ParentPlanError(
            "child selection policy differs from the parent outside base_content_units"
        )
    return parent_policy


def _inherits_resolution(
    parent_policy: SelectionPolicy, child: SelectionPolicy
) -> bool:
    """Whether the child declares the same policy as its resolved parent.
    A plan embeds its policy *with bands resolved*, so a draft that derives bands
    inherits the parent's while one declaring them must declare the same ones.
    """
    parent_fields = _inherited_policy_fields(parent_policy)
    child_fields = _inherited_policy_fields(child)
    if child.derives_era_bands:
        child_fields.pop("era_bands", None)
        parent_fields.pop("era_bands", None)
    return parent_fields == child_fields


def _child_policy(
    policy: SelectionPolicy,
    base: SelectionPolicy,
    target_units: int,
    parent_meta: dict[str, Any],
    recorded_fingerprint: str,
) -> SelectionPolicy:
    return replace(
        base,
        base_content_units=target_units,
        level=max(policy.level, int(parent_meta.get("level", 1)) + 1),
        parent_plan_id=str(parent_meta["plan_id"]),
        parent_plan_fingerprint=recorded_fingerprint,
    )


def prepare_parent(
    parent_plan_dir: str | Path,
    policy: SelectionPolicy,
    target_units: int,
    catalog_id: str,
    seed_fingerprint: str,
) -> tuple[dict[str, Any], list[str], SelectionPolicy]:
    """Validate a parent and derive the child policy that extends it."""
    parent_root = Path(parent_plan_dir).resolve()
    parent_meta = _read_plan_json(parent_root)
    parent_keys = plan_locator_keys(parent_root)

    # Re-run for direct callers: ``expand`` gates before reading the sidecar,
    # and this is a public entry point of its own.
    validate_parent_schema(parent_meta)

    if target_units < len(parent_keys):
        raise ParentPlanError(
            "expanded target_units cannot be smaller than the parent selection"
        )

    # Checked against the selection the parent actually published, not merely
    # read: a parent whose fingerprint disagrees with its own locators is not the
    # plan it claims to be.
    recorded_fingerprint = str(parent_meta["plan_fingerprint"])
    if plan_fingerprint(parent_meta, parent_keys) != recorded_fingerprint:
        raise ParentPlanError(
            "parent plan fingerprint does not match its published selection; "
            "the bundle was modified after publication"
        )

    # Validated against the caller's declaration, then again against the
    # parent's resolved policy, which is what makes the child inherit the bands
    # its parent was stratified under.
    child_policy = _child_policy(
        policy, policy, target_units, parent_meta, recorded_fingerprint
    )
    parent_policy = validate_parent(
        parent_meta, None, child_policy, catalog_id, seed_fingerprint
    )
    if parent_policy is not None:
        child_policy = _child_policy(
            policy, parent_policy, target_units, parent_meta, recorded_fingerprint
        )
        validate_parent(
            parent_meta, parent_policy, child_policy, catalog_id, seed_fingerprint
        )
    return parent_meta, parent_keys, child_policy


def validate_target(
    parent_plan_dir: str | Path | None, selected_count: int, target_units: int
) -> None:
    """Refuse to publish a child that could not reach its requested size.

    Only meaningful for an expansion; a fresh plan reports the shortfall instead.
    """
    if parent_plan_dir is not None and selected_count < target_units:
        raise ParentPlanError(
            "expanded selection could not reach target_units; no child plan was "
            "published"
        )


def read_expansion_metadata(plan_dir: str | Path) -> dict[str, Any]:
    """Return a plan's lineage record, or an empty mapping for a root plan."""
    path = Path(plan_dir).resolve() / EXPANSION_METADATA_FILE
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def expand(
    parent_plan_dir: str | Path,
    target_units: int,
    *,
    artifacts_root: str | Path | None = None,
    seed_filers: dict[str, Any] | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    """Publish an immutable child plan that retains every parent locator.

    A ``target_units`` below the parent's is a contraction, and is rejected.
    """
    if target_units < 1:
        raise ValueError("target_units must be positive")

    paths = (
        resolve_filing_catalog_paths(artifacts_root)
        if artifacts_root is not None
        else resolve_filing_catalog_paths()
    )
    parent_root = Path(parent_plan_dir).resolve()
    parent_meta = _read_plan_json(parent_root)

    # Scope first, so a deterministic plan gets the error explaining *why* it
    # cannot be expanded; then schema, before the seed sidecar is touched.
    if parent_meta.get("scope") != SCOPE_POLICY:
        raise ParentPlanError("plan expansion requires a policy-driven parent plan")

    validate_parent_schema(parent_meta)

    catalog_id = str(parent_meta["catalog_id"])

    embedded = parent_meta.get("selection_policy")
    if not isinstance(embedded, dict):
        raise ParentPlanError(
            "parent plan does not record its selection policy; it cannot be expanded"
        )
    parent_policy = SelectionPolicy.from_dict(embedded)

    if seed_filers is None:
        # An expansion must reproduce its parent's selection, so the seed set comes
        # from the parent's sidecar: re-reading the configured CSV would let a
        # moved or edited file change a child whose parent is not reproducible.
        seed_filers = _read_parent_seed_filers(
            paths, str(parent_meta["plan_id"]), parent_root
        )
    seed_fingerprint = compute_seed_fingerprint(seed_filers)
    _parent_meta, parent_keys, child_policy = prepare_parent(
        parent_root, parent_policy, target_units, catalog_id, seed_fingerprint
    )

    # From the parent, so a child cannot silently narrow the surface its parent
    # committed to.
    child_policy.document_suffixes = list(
        normalize_suffixes(parent_policy.document_suffixes)
    )

    child_meta = plan_policy(
        catalog_id,
        child_policy,
        artifacts_root,
        seed_filers=seed_filers,
        parent_active_keys=parent_keys,
        progress=progress,
    )
    validate_target(parent_root, int(child_meta["unique_locators_count"]), target_units)

    lineage = ExpansionLineage(
        parent_plan_id=child_policy.parent_plan_id or "",
        parent_plan_fingerprint=child_policy.parent_plan_fingerprint or "",
        target_units=target_units,
        parent_locator_count=len(parent_keys),
        child_locator_count=int(child_meta["unique_locators_count"]),
    )
    child_dir = paths.plan_dir(str(child_meta["plan_id"]))
    _write_lineage(child_dir, lineage, child_meta)
    child_meta["parent_plan_id"] = lineage.parent_plan_id
    child_meta["parent_plan_fingerprint"] = lineage.parent_plan_fingerprint
    _rewrite_plan_json(child_dir, child_meta)
    return child_meta


def _write_lineage(
    plan_dir: Path, lineage: ExpansionLineage, child_meta: dict[str, Any]
) -> None:
    record = lineage.to_dict()
    record["child_plan_id"] = child_meta["plan_id"]
    record["catalog_id"] = child_meta["catalog_id"]
    atomic_write_json(
        plan_dir / EXPANSION_METADATA_FILE, record, canonical=False, indent=2
    )


def _rewrite_plan_json(plan_dir: Path, child_meta: dict[str, Any]) -> None:
    """Add the lineage keys to the published ``plan.json`` in place.
    It only ever gains keys, so a concurrent reader sees the pre- or post-lineage
    document, never a partial one.
    """
    atomic_write_json(plan_dir / PLAN_FILE_NAME, child_meta, canonical=False, indent=2)


__all__ = [
    "ExpansionLineage",
    "ParentPlanError",
    "expand",
    "prepare_parent",
    "read_expansion_metadata",
    "validate_parent",
    "validate_parent_schema",
    "validate_target",
]
