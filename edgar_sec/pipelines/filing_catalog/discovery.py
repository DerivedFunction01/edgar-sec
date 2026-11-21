"""Discovery of published catalogs, target plans, and selection policies.
Catalog state comes from the DAG database; plan bundles remain file artifacts.
Year bounds are computed from the published target relation when requested.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.filters import DateSelection
from edgar_sec.engine.selection.policy import (
    SelectionPolicy,
    auto_generate_policy,
)
from edgar_sec.engine.selection.policy import (
    discover_policies as scan_policies,
)
from edgar_sec.engine.selection.predicates import (
    date_selection_sql,
    parsed_date_relation,
)
from edgar_sec.domain.plan.discovery import (
    discover_plans as _discover_plans,
)
from edgar_sec.foundation.runtime.paths import PARQUET_PART_GLOB
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.duckdb import connect, sql_literal
from edgar_sec.pipelines.filing_catalog.envelope import CatalogPlanEnvelope
from edgar_sec.pipelines.filing_catalog.paths import (
    CURRENT_ALIAS,
    FilingCatalogPaths,
    resolve_filing_catalog_paths,
    validate_safe_id,
)
from edgar_sec.pipelines.filing_catalog.publication import PlanConflictError

# EDGAR's full-text coverage begins in 1994
_MIN_PLAUSIBLE_YEAR = 1990


def current_catalog_id(paths: FilingCatalogPaths) -> str | None:
    """Return the catalog id named by the current pointer, if any.

    The DAG catalog is the single authority for the published tip.
    """
    try:
        catalog = DAGCatalog(paths.snapshots_root, read_only=True)
    except FileNotFoundError:
        return None
    ptr = catalog.read_pointer()
    return str(ptr["snapshot_id"]) if ptr else None


def resolve_catalog_reference(paths: FilingCatalogPaths, catalog: str) -> str:
    """Resolve a catalog reference to a concrete catalog id.

    A literal id is validated as a path segment, so it cannot escape the tree.
    """
    if catalog == CURRENT_ALIAS:
        resolved = current_catalog_id(paths)
        if resolved is None:
            raise PlanConflictError(
                "no catalog is published as current; pass an explicit catalog id"
            )
        return resolved
    return validate_safe_id(catalog)


def discover_catalogs(
    paths: FilingCatalogPaths | None = None,
) -> list[dict[str, Any]]:
    """List every published catalog snapshot, newest id last."""
    resolved = paths or resolve_filing_catalog_paths()
    try:
        catalog = DAGCatalog(resolved.snapshots_root, read_only=True)
    except FileNotFoundError:
        return []
    found: list[dict[str, Any]] = []
    for node_info in catalog.list_snapshots():
        catalog_id = str(node_info["snapshot_id"])
        node = catalog.get_manifest(catalog_id)
        if node is None:
            continue
        metadata = node.metadata
        target_parts = node.relations.get("filing_targets", ())
        profile_parts = node.relations.get("company_profiles", ())
        found.append(
            {
                "catalog_id": catalog_id,
                "profile_row_count": sum(part.row_count for part in profile_parts),
                "target_row_count": sum(part.row_count for part in target_parts),
                "schema_version": node.schema_versions.get("filing_targets"),
                "part_count": len(target_parts),
                "form_counts": metadata.get("form_counts") or {},
                "source_artifact": metadata.get("source_artifact"),
            }
        )
    return found


def discover_plans(
    paths: FilingCatalogPaths | None = None,
) -> list[CatalogPlanEnvelope]:
    """List every published target-plan bundle."""
    resolved = paths or resolve_filing_catalog_paths()
    return _discover_plans(resolved.plans_root, envelope_cls=CatalogPlanEnvelope)


def policy_search_dirs(paths: FilingCatalogPaths | None = None) -> list[Path]:
    """Directories a selection policy may be published in.

    The pipeline root is scanned too; anything not parsing as a policy is skipped.
    """
    resolved = paths or resolve_filing_catalog_paths()
    return [resolved.policies_root, resolved.catalog_root]


def discover_policies(paths: FilingCatalogPaths | None = None) -> list[dict[str, Any]]:
    """List every valid selection policy published under the catalog root."""
    return scan_policies(policy_search_dirs(paths))


def auto_policy(
    catalog: str,
    paths: FilingCatalogPaths | None = None,
    dest: Path | None = None,
) -> SelectionPolicy:
    """Derive a baseline policy from a published catalog's own forms and years."""
    resolved = paths or resolve_filing_catalog_paths()
    catalog_id = resolve_catalog_reference(resolved, catalog)
    manifests = discover_catalogs(resolved)
    manifest = next((m for m in manifests if m.get("catalog_id") == catalog_id), {})
    forms = list((manifest.get("form_counts") or {}).keys())
    min_year, max_year = catalog_year_bounds(resolved, catalog_id)
    return auto_generate_policy(catalog_id, forms, min_year, max_year, dest=dest)


def _year_bounds_query(
    relation: str,
    *,
    forms: Sequence[str] | None = None,
    date_selection: DateSelection = (),
) -> str:
    """Return the year-bound query over ``relation``, optionally narrowed.
    A nonempty selection filters on the parsed alias, so the relation is wrapped here
    and cannot drift from the predicate.
    """
    clauses = [
        "report_date IS NOT NULL",
        "length(report_date) >= 4",
        (
            f"CAST(substring(report_date, 1, 4) AS INTEGER)"
            f" BETWEEN {_MIN_PLAUSIBLE_YEAR} AND {_current_year()}"
        ),
    ]
    if forms:
        form_list = ", ".join(sql_literal(form) for form in sorted(forms))
        clauses.append(f"form IN ({form_list})")
    source = relation
    if date_selection:
        clauses.append(date_selection_sql(date_selection))
        source = parsed_date_relation(relation, "report_date")
    return f"""
        SELECT
            MIN(CAST(substring(report_date, 1, 4) AS INTEGER)),
            MAX(CAST(substring(report_date, 1, 4) AS INTEGER))
        FROM {source}
        WHERE {" AND ".join(clauses)}
    """


def _current_year() -> int:
    import datetime

    return datetime.datetime.now(datetime.UTC).year


def _target_relation(paths: FilingCatalogPaths, catalog_id: str) -> str | None:
    """Return the catalog's targets as one relation, or ``None`` when absent."""
    target_files = sorted(
        paths.snapshot_targets_dir(catalog_id).glob(PARQUET_PART_GLOB)
    )
    if not target_files:
        return None
    file_list = ", ".join(sql_literal(str(path)) for path in target_files)
    return f"read_parquet([{file_list}])"


def catalog_year_bounds(paths: FilingCatalogPaths, catalog_id: str) -> tuple[int, int]:
    """Return the observed report-year range of a catalog, clipped to EDGAR.
    The fallback for a selection reaching nothing: bands still must be published, and
    the honest ones come from every year the catalog holds.
    """
    current_year = _current_year()
    relation = _target_relation(paths, catalog_id)
    if relation is None:
        return current_year - 10, current_year
    with connect() as con:
        row = con.execute(_year_bounds_query(relation)).fetchone()
    minimum = int(row[0]) if row and row[0] is not None else current_year - 10
    maximum = int(row[1]) if row and row[1] is not None else current_year
    return minimum, maximum


def eligible_year_bounds(
    paths: FilingCatalogPaths,
    catalog_id: str,
    *,
    forms: Sequence[str] | None = None,
    date_selection: DateSelection = (),
) -> tuple[int, int] | None:
    """Return the report-year range a selection can reach, or ``None``.
    ``None`` rather than a synthetic range: "matches no dated row" is handled
    differently from "the catalog is narrow".
    """
    relation = _target_relation(paths, catalog_id)
    if relation is None:
        return None
    query = _year_bounds_query(relation, forms=forms, date_selection=date_selection)
    with connect() as con:
        row = con.execute(query).fetchone()
    if not row or row[0] is None or row[1] is None:
        return None
    return int(row[0]), int(row[1])


def status(paths: FilingCatalogPaths | None = None) -> dict[str, Any]:
    """Summarize published state from the DAG catalog and plan bundles."""
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
    "catalog_year_bounds",
    "current_catalog_id",
    "discover_catalogs",
    "discover_plans",
    "discover_policies",
    "eligible_year_bounds",
    "policy_search_dirs",
    "resolve_catalog_reference",
    "status",
]
