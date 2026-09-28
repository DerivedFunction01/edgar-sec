"""Parent-plan validation and immutable target-plan expansion.

Expansion scales a published policy plan from ``N`` to ``M > N`` locators
without discarding anything the parent already selected. The invariant is
strict: **the child contains 100% of the parent's locators.** A scale-up that
quietly resamples is worse than no scale-up at all, because a downstream
acquisition would skip documents the parent plan had already committed to and
the gap would only surface as missing documents in the store.

Two things make that guarantee hold rather than merely be intended:

* The child's selection runs with the parent's keys as ``parent_active_keys``,
  so the parent's locators are in the exclusion set before any candidate pool
  is drawn. No pool query can offer one of them again.
* The child's own compatibility with the parent is checked *before* any
  selection runs, so a mismatched catalog, corpus, form set, or seed set fails
  immediately instead of after an expensive build.

The lineage record lands in ``expansion_metadata.json`` beside the plan, and
the child records ``parent_plan_id`` and ``parent_plan_fingerprint`` in
``plan.json``, so a plan's provenance is readable from the plan itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.filters import normalize_suffixes
from edgar_sec.engine.selection.policy import SelectionPolicy, compute_seed_fingerprint
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.duckdb_catalog import sql_literal
from edgar_sec.pipelines.filing_catalog.paths import (
    EXPANSION_METADATA_NAME,
    LOCATOR_GROUPS_NAME,
    PLAN_FILE_NAME,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planner import SCOPE_POLICY, plan_policy

# Fields that legitimately differ between a parent and its child. Everything
# else must match, or the two plans were built against different intents and
# combining their selections would be meaningless.
_CHILD_ONLY_FIELDS = (
    "base_content_units",
    "level",
    "parent_plan_id",
    "parent_plan_fingerprint",
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


def plan_fingerprint(plan_meta: dict[str, Any], locator_keys: list[str]) -> str:
    """Content digest of a plan's identity and its selected locators.

    Binds the fingerprint to the *selection*, not just the request, so two runs
    that requested the same thing but selected differently do not share an id.
    """
    return canonical_hash(
        {
            "plan_id": plan_meta.get("plan_id"),
            "catalog_id": plan_meta.get("catalog_id"),
            "scope": plan_meta.get("scope"),
            "locator_keys": sorted(locator_keys),
        }
    )[:32]


def plan_locator_keys(plan_dir: str | Path) -> list[str]:
    """Read a published plan's selected locator keys, in file order.

    An in-memory DuckDB connection is used rather than a database file beside
    the plan: v1 wrote ``parent_plan_read.duckdb`` into the plan directory and
    deleted it afterwards, so an interrupted read left stray state inside an
    immutable published bundle.
    """
    root = Path(plan_dir).resolve()
    locator_path = root / LOCATOR_GROUPS_NAME
    if not locator_path.is_file():
        raise FileNotFoundError(f"parent plan locator groups not found: {locator_path}")
    with connect() as con:
        rows = con.execute(
            f"SELECT document_locator_key FROM read_parquet("
            f"{sql_literal(str(locator_path))}) ORDER BY document_locator_key"
        ).fetchall()
    return [str(row[0]) for row in rows]


def _read_plan_json(plan_dir: Path) -> dict[str, Any]:
    path = plan_dir / PLAN_FILE_NAME
    if not path.is_file():
        raise ParentPlanError(f"parent plan has no {PLAN_FILE_NAME}: {plan_dir}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ParentPlanError(f"parent plan.json is unreadable: {plan_dir}") from error


def _compatibility_key(policy: SelectionPolicy) -> dict[str, Any]:
    """The policy fields a child must inherit unchanged from its parent."""
    data = policy.to_dict()
    for field_name in _CHILD_ONLY_FIELDS:
        data.pop(field_name, None)
    return data


def validate_parent(
    parent_meta: dict[str, Any],
    parent_policy: SelectionPolicy | None,
    policy: SelectionPolicy,
    catalog_id: str,
    seed_fingerprint: str,
) -> None:
    """Reject a child policy that does not extend its parent.

    Checked before selection so a mismatched expansion costs a validation error
    rather than a full feature build. A deterministic plan has no selection to
    extend, so it is refused outright.
    """
    if parent_meta.get("scope") != SCOPE_POLICY:
        raise ParentPlanError("plan expansion requires a policy-driven parent plan")
    if str(parent_meta.get("catalog_id")) != catalog_id:
        raise ParentPlanError("parent and child plans must use the same catalog")
    if parent_meta.get("policy_corpus") not in (None, policy.corpus_id):
        raise ParentPlanError("parent and child plans must use the same policy corpus")
    if parent_meta.get("seed_fingerprint") not in (None, seed_fingerprint):
        raise ParentPlanError("parent and child plans must use the same seed CIK set")

    parent_forms = {str(form).upper() for form in parent_meta.get("forms") or []}
    child_forms = {str(form).upper() for form in policy.forms}
    if parent_forms and parent_forms != child_forms:
        raise ParentPlanError("parent and child plans must use the same forms")

    if parent_policy is None:
        embedded = parent_meta.get("selection_policy")
        if isinstance(embedded, dict):
            parent_policy = SelectionPolicy.from_dict(embedded)
    if parent_policy is not None and _compatibility_key(
        parent_policy
    ) != _compatibility_key(policy):
        raise ParentPlanError(
            "child selection policy differs from the parent outside base_content_units"
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

    if target_units < len(parent_keys):
        raise ParentPlanError(
            "expanded target_units cannot be smaller than the parent selection"
        )

    child_policy = replace(
        policy,
        base_content_units=target_units,
        level=max(policy.level, int(parent_meta.get("level", 1)) + 1),
        parent_plan_id=str(parent_meta.get("plan_id") or parent_root.name),
        parent_plan_fingerprint=str(
            parent_meta.get("plan_fingerprint")
            or plan_fingerprint(parent_meta, parent_keys)
        ),
    )
    validate_parent(parent_meta, None, child_policy, catalog_id, seed_fingerprint)
    return parent_meta, parent_keys, child_policy


def validate_target(
    parent_plan_dir: str | Path | None, selected_count: int, target_units: int
) -> None:
    """Refuse to publish a child that could not reach its requested size.

    Only meaningful for an expansion: a fresh policy plan publishes whatever the
    corpus could supply, with the shortfall reported rather than fatal.
    """
    if parent_plan_dir is not None and selected_count < target_units:
        raise ParentPlanError(
            "expanded selection could not reach target_units; no child plan was "
            "published"
        )


def read_expansion_metadata(plan_dir: str | Path) -> dict[str, Any]:
    """Return a plan's lineage record, or an empty mapping for a root plan."""
    path = Path(plan_dir).resolve() / EXPANSION_METADATA_NAME
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

    ``target_units`` is the child's requested size. It must be at least the
    parent's selected locator count; a smaller request is a contraction, not an
    expansion, and is rejected rather than silently truncated.
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

    # Check the scope before anything else, so a deterministic plan gets the
    # error that explains *why* it cannot be expanded rather than a complaint
    # about the policy field it was never going to have.
    if parent_meta.get("scope") != SCOPE_POLICY:
        raise ParentPlanError("plan expansion requires a policy-driven parent plan")

    catalog_id = str(parent_meta.get("catalog_id") or "")
    if not catalog_id:
        raise ParentPlanError("parent plan is missing catalog_id")

    embedded = parent_meta.get("selection_policy")
    if not isinstance(embedded, dict):
        raise ParentPlanError(
            "parent plan does not record its selection policy; it cannot be expanded"
        )
    parent_policy = SelectionPolicy.from_dict(embedded)

    seed_fingerprint = compute_seed_fingerprint(seed_filers or {})
    _parent_meta, parent_keys, child_policy = prepare_parent(
        parent_root, parent_policy, target_units, catalog_id, seed_fingerprint
    )

    # The catalog id and the form/suffix vocabulary come from the parent, so a
    # child cannot silently narrow the surface its parent committed to.
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
        plan_dir / EXPANSION_METADATA_NAME, record, canonical=False, indent=2
    )


def _rewrite_plan_json(plan_dir: Path, child_meta: dict[str, Any]) -> None:
    """Add the lineage keys to the published ``plan.json`` in place.

    The bundle is already published by the time the lineage is known, because
    the lineage is a function of the selection the plan just recorded. The file
    is rewritten atomically and only ever gains keys, so a concurrent reader
    sees either the pre-lineage or the post-lineage document, never a partial
    one.
    """
    atomic_write_json(plan_dir / PLAN_FILE_NAME, child_meta, canonical=False, indent=2)


__all__ = [
    "ExpansionLineage",
    "ParentPlanError",
    "expand",
    "plan_fingerprint",
    "plan_locator_keys",
    "prepare_parent",
    "read_expansion_metadata",
    "validate_parent",
    "validate_target",
]
