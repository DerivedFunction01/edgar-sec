"""Manifest-only discovery of published catalogs and target plans.

Every function here reads JSON manifests and directory listings only. It never
opens a Parquet payload, never materializes a catalog, and never contacts the
network, so ``status`` stays cheap enough to call from a menu loop or a
preflight check.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.engine.selection.policy import (
    SelectionPolicy,
    auto_generate_policy,
)
from edgar_sec.engine.selection.policy import (
    discover_policies as scan_policies,
)
from edgar_sec.infra.storage.duckdb_catalog import sql_literal
from edgar_sec.pipelines.filing_catalog.paths import (
    CURRENT_ALIAS,
    PLAN_FILE_NAME,
    POLICIES_DIR_NAME,
    SNAPSHOT_MANIFEST_NAME,
    FilingCatalogPaths,
    resolve_filing_catalog_paths,
    safe_identifier,
)
from edgar_sec.pipelines.filing_catalog.publication import PlanConflictError

# EDGAR's full-text coverage begins in 1994 and 1990 is a safe lower bound for
# "a plausible filing year"; anything earlier in a report_date is bad data and
# would otherwise stretch the generated era bands across empty decades.
_MIN_PLAUSIBLE_YEAR = 1990


def _read_json(path: Path) -> dict[str, Any] | None:
    """Return parsed JSON, or None when absent or unreadable.

    A truncated manifest is reported as absent rather than raising, so a single
    damaged directory cannot make discovery fail for every other entry.
    """
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def current_catalog_id(paths: FilingCatalogPaths) -> str | None:
    """Return the catalog id named by the current pointer, if any."""
    pointer = _read_json(paths.current_pointer)
    if pointer is None:
        return None
    catalog_id = pointer.get("catalog_id") or pointer.get("snapshot_id")
    return str(catalog_id) if catalog_id else None


def resolve_catalog_manifest(
    paths: FilingCatalogPaths, catalog: str
) -> dict[str, Any] | None:
    """Resolve a catalog id, or the literal ``current``, to its manifest."""
    if catalog == CURRENT_ALIAS:
        catalog_id = current_catalog_id(paths)
        if catalog_id is None:
            return None
    else:
        catalog_id = safe_identifier(catalog)
    return _read_json(paths.snapshot_manifest(catalog_id))


def resolve_catalog_reference(paths: FilingCatalogPaths, catalog: str) -> str:
    """Resolve a catalog reference to a concrete catalog id.

    Accepts a literal id or the ``current`` alias, which the pointer resolves.
    A literal id is validated as a path segment, so a caller-supplied string can
    never escape the snapshots tree.

    This lives in ``discovery`` rather than ``planner`` because resolving a
    reference against the published pointer is the same question
    :func:`current_catalog_id` and :func:`discover_catalogs` answer, and three
    callers now need it.
    """
    if catalog == CURRENT_ALIAS:
        resolved = current_catalog_id(paths)
        if resolved is None:
            raise PlanConflictError(
                "no catalog is published as current; pass an explicit catalog id"
            )
        return resolved
    return safe_identifier(catalog)


def discover_catalogs(
    paths: FilingCatalogPaths | None = None,
) -> list[dict[str, Any]]:
    """List every published catalog snapshot, newest id last.

    Results are sorted by catalog id for a stable presentation order; the id is
    content-derived, so lexical order is meaningful and reproducible.
    """
    resolved = paths or resolve_filing_catalog_paths()
    found: list[dict[str, Any]] = []
    if not resolved.snapshots_root.is_dir():
        return found
    for entry in sorted(resolved.snapshots_root.iterdir()):
        if not entry.is_dir() or entry.name == CURRENT_ALIAS:
            continue
        manifest = _read_json(entry / SNAPSHOT_MANIFEST_NAME)
        if manifest is None:
            continue
        found.append(
            {
                "catalog_id": entry.name,
                "profile_row_count": manifest.get("profile_row_count"),
                "target_row_count": manifest.get("target_row_count"),
                "schema_version": manifest.get("schema_version"),
                "part_count": len(manifest.get("parts") or []),
                "form_counts": manifest.get("form_counts") or {},
                "source_artifact": manifest.get("source_artifact"),
            }
        )
    return found


def discover_plans(paths: FilingCatalogPaths | None = None) -> list[dict[str, Any]]:
    """List every published target-plan bundle."""
    resolved = paths or resolve_filing_catalog_paths()
    found: list[dict[str, Any]] = []
    if not resolved.plans_root.is_dir():
        return found
    for entry in sorted(resolved.plans_root.iterdir()):
        if not entry.is_dir():
            continue
        plan = _read_json(entry / PLAN_FILE_NAME)
        if plan is None:
            continue
        found.append(
            {
                "plan_id": entry.name,
                "catalog_id": plan.get("catalog_id"),
                "scope": plan.get("scope"),
                "forms": plan.get("forms") or [],
                "amendment": plan.get("amendment"),
                "document_suffixes": plan.get("document_suffixes") or [],
                "limit": plan.get("limit"),
                "selected_rows": plan.get("selected_rows"),
                "unique_locators_count": plan.get("unique_locators_count"),
                "counts": plan.get("counts") or {},
                "target_units": plan.get("target_units"),
                "parent_plan_id": plan.get("parent_plan_id"),
                "policy_fingerprint": plan.get("policy_fingerprint"),
            }
        )
    return found


def policy_search_dirs(paths: FilingCatalogPaths | None = None) -> list[Path]:
    """Directories a selection policy may be published in.

    The layout lives in Layer 4, so the engine cannot resolve it; this is the
    resolver that hands explicit directories to the engine-level scan.
    """
    resolved = paths or resolve_filing_catalog_paths()
    policies_root = resolved.catalog_root / POLICIES_DIR_NAME
    return [policies_root, resolved.catalog_root]


def discover_policies(paths: FilingCatalogPaths | None = None) -> list[dict[str, Any]]:
    """List every valid selection policy published under the catalog root."""
    return scan_policies(policy_search_dirs(paths))


def auto_policy(
    catalog: str,
    paths: FilingCatalogPaths | None = None,
    dest: Path | None = None,
) -> SelectionPolicy:
    """Derive a baseline policy from a published catalog's own forms and years.

    The engine derives the policy from observed data; locating that data is a
    layout concern, so it is resolved here.
    """
    resolved = paths or resolve_filing_catalog_paths()
    catalog_id = resolve_catalog_reference(resolved, catalog)
    manifests = discover_catalogs(resolved)
    manifest = next((m for m in manifests if m.get("catalog_id") == catalog_id), {})
    forms = list((manifest.get("form_counts") or {}).keys())
    min_year, max_year = _catalog_year_bounds(resolved, catalog_id)
    return auto_generate_policy(catalog_id, forms, min_year, max_year, dest=dest)


def _catalog_year_bounds(paths: FilingCatalogPaths, catalog_id: str) -> tuple[int, int]:
    """Return the observed report-year range of a catalog, clipped to EDGAR."""
    import datetime

    from edgar_sec.infra.storage.duckdb import connect

    current_year = datetime.datetime.now(datetime.UTC).year
    target_files = sorted(paths.snapshot_targets_dir(catalog_id).glob("part-*.parquet"))
    if not target_files:
        return current_year - 10, current_year

    file_list = ", ".join(sql_literal(str(path)) for path in target_files)
    with connect() as con:
        row = con.execute(
            f"""
            SELECT
                MIN(CAST(substring(report_date, 1, 4) AS INTEGER)),
                MAX(CAST(substring(report_date, 1, 4) AS INTEGER))
            FROM read_parquet([{file_list}])
            WHERE report_date IS NOT NULL
              AND length(report_date) >= 4
              AND CAST(substring(report_date, 1, 4) AS INTEGER)
                  BETWEEN {_MIN_PLAUSIBLE_YEAR} AND {current_year}
            """
        ).fetchone()
    minimum = int(row[0]) if row and row[0] is not None else current_year - 10
    maximum = int(row[1]) if row and row[1] is not None else current_year
    return minimum, maximum


def status(paths: FilingCatalogPaths | None = None) -> dict[str, Any]:
    """Summarize published state from manifests alone."""
    resolved = paths or resolve_filing_catalog_paths()
    catalogs = discover_catalogs(resolved)
    plans = discover_plans(resolved)
    current = current_catalog_id(resolved)
    return {
        "artifacts_root": str(resolved.artifacts_root),
        "current_catalog_id": current,
        "catalog_count": len(catalogs),
        "plan_count": len(plans),
        "catalogs": catalogs,
        "plans": plans,
        "total_planned_rows": sum(
            int(plan.get("selected_rows") or 0) for plan in plans
        ),
    }


__all__ = [
    "CURRENT_ALIAS",
    "auto_policy",
    "current_catalog_id",
    "discover_catalogs",
    "discover_plans",
    "discover_policies",
    "policy_search_dirs",
    "resolve_catalog_manifest",
    "resolve_catalog_reference",
    "status",
]
