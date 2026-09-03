"""Parent-plan validation and immutable fixture-plan expansion."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

from defs.storage import DuckDBStaging, canonical_json, load_json

from .selection_policy import SelectionPolicy


def plan_fingerprint(plan_meta: dict[str, Any], locator_keys: list[str]) -> str:
    payload = {
        "plan_id": plan_meta.get("plan_id"),
        "catalog_id": plan_meta.get("catalog_id"),
        "scope": plan_meta.get("scope"),
        "locator_keys": locator_keys,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:32]


def plan_locator_keys(plan_dir: str | Path) -> list[str]:
    """Read active locator keys from an existing target-plan bundle."""
    root = Path(plan_dir).resolve()
    locator_path = root / "locator_groups.parquet"
    if not locator_path.is_file():
        raise FileNotFoundError(f"parent plan locator groups not found: {locator_path}")
    staging_path = root / "parent_plan_read.duckdb"
    try:
        with DuckDBStaging(staging_path, cleanup_root=False) as staging:
            rows = staging.execute(
                f"""
                SELECT document_locator_key
                FROM read_parquet('{locator_path}')
                ORDER BY document_locator_key
                """
            )
        return [str(row[0]) for row in rows]
    finally:
        staging_path.unlink(missing_ok=True)


def _policy_compatibility_key(policy: SelectionPolicy) -> dict[str, Any]:
    data = policy.to_dict()
    for field_name in (
        "base_content_units",
        "level",
        "parent_plan_id",
        "parent_plan_fingerprint",
    ):
        data.pop(field_name, None)
    return data


def _validate_parent(
    parent_meta: dict[str, Any],
    parent_policy: SelectionPolicy | None,
    policy: SelectionPolicy,
    catalog_id: str,
    seed_fingerprint: str,
) -> None:
    if parent_meta.get("scope") != "fixture":
        raise ValueError("plan expansion requires a fixture-scope parent plan")
    if str(parent_meta.get("catalog_id")) != catalog_id:
        raise ValueError("parent and child plans must use the same catalog")
    if parent_meta.get("policy_corpus") not in (None, policy.corpus_id):
        raise ValueError("parent and child plans must use the same policy corpus")
    parent_forms = {str(form).upper() for form in parent_meta.get("forms", [])}
    child_forms = {str(form).upper() for form in policy.forms}
    if parent_forms and parent_forms != child_forms:
        raise ValueError("parent and child plans must use the same forms")
    if parent_meta.get("seed_fingerprint") not in (None, seed_fingerprint):
        raise ValueError("parent and child plans must use the same seed CIK set")
    if parent_policy is not None and _policy_compatibility_key(parent_policy) != (
        _policy_compatibility_key(policy)
    ):
        raise ValueError(
            "child selection policy differs from the parent outside base_content_units"
        )


def prepare_parent(
    parent_plan_dir: str | Path,
    policy: SelectionPolicy,
    target_units: int,
    catalog_id: str,
    seed_fingerprint: str,
) -> tuple[dict[str, Any], list[str], SelectionPolicy]:
    parent_root = Path(parent_plan_dir).resolve()
    parent_meta = load_json(parent_root / "plan.json")
    parent_keys = plan_locator_keys(parent_root)
    if target_units < len(parent_keys):
        raise ValueError(
            "expanded target_units cannot be smaller than the parent selection"
        )
    embedded_policy = parent_meta.get("selection_policy")
    parent_policy = (
        SelectionPolicy.from_dict(embedded_policy)
        if isinstance(embedded_policy, dict)
        else None
    )
    child_policy = replace(
        policy,
        base_content_units=target_units,
        level=max(policy.level, int(parent_meta.get("level", 1)) + 1),
        parent_plan_id=str(parent_meta.get("plan_id") or ""),
        parent_plan_fingerprint=str(
            parent_meta.get("plan_fingerprint")
            or plan_fingerprint(parent_meta, parent_keys)
        ),
    )
    _validate_parent(
        parent_meta, parent_policy, child_policy, catalog_id, seed_fingerprint
    )
    return parent_meta, parent_keys, child_policy


def validate_target(
    parent_plan_dir: str | Path | None,
    selected_count: int,
    target_units: int,
) -> None:
    if parent_plan_dir is not None and selected_count < target_units:
        raise ValueError(
            "expanded selection could not reach target_units; no child plan was published"
        )


def expansion_metadata(
    policy: SelectionPolicy,
    parent_meta: dict[str, Any] | None,
    parent_keys: list[str],
    selected_keys: list[str],
) -> dict[str, Any]:
    if parent_meta is None:
        return {}
    return {
        "parent_plan_id": policy.parent_plan_id,
        "parent_plan_fingerprint": policy.parent_plan_fingerprint,
        "target_units": policy.base_content_units,
        "added_locators_count": len(selected_keys) - len(parent_keys),
    }


def expand(
    parent_plan: str | Path,
    target_units: int,
    *,
    selection_policy_path: str | Path | None = None,
    seed_cik_path: str | Path | None = None,
    output_root: str | None = None,
    progress=None,
) -> dict[str, Any]:
    """Create an immutable fixture child plan with the parent selection retained."""
    if target_units < 1:
        raise ValueError("target_units must be positive")
    parent_meta = load_json(Path(parent_plan).resolve() / "plan.json")
    catalog_id = parent_meta.get("catalog_id")
    if not catalog_id:
        raise ValueError("parent plan is missing catalog_id")
    from .target_plan import plan

    return plan(
        str(catalog_id),
        output_root,
        scope="fixture",
        selection_policy_path=selection_policy_path,
        seed_cik_path=seed_cik_path,
        progress=progress,
        parent_plan_dir=parent_plan,
        target_units=target_units,
    )


__all__ = [
    "expand",
    "expansion_metadata",
    "plan_fingerprint",
    "plan_locator_keys",
    "prepare_parent",
    "validate_target",
]
