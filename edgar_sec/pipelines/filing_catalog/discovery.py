"""Discovery of published catalogs, target plans, and selection policies.

Most of this module reads JSON manifests and directory listings only, so
``status`` stays cheap enough to call from a menu loop or a preflight check.
The year-bound helpers are the exception: they run one aggregate over the
catalog's own target shards, because the report-year range is not recorded
anywhere a manifest could answer it.
"""

from __future__ import annotations

import json
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
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.duckdb_catalog import (
    date_selection_sql,
    parsed_date_relation,
    sql_literal,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    CURRENT_ALIAS,
    PLAN_FILE_NAME,
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
        # ``current`` is the pointer, and a Stage B feature snapshot is also a
        # directory here; both are told apart by what they do not hold. Only a
        # directory carrying snapshot.manifest.json is a catalog snapshot.
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

    ``policies/`` is the declared location; the pipeline root is also scanned so a
    policy dropped there is still found. The root holds only directories
    (``snapshots/``, ``plans/``, ``policies/``) and the scan skips anything that
    does not parse as a policy, so the extra entry cannot surface a false match.

    The layout lives in Layer 4, so the engine cannot resolve it; this is the
    resolver that hands explicit directories to the engine-level scan.
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
    """Derive a baseline policy from a published catalog's own forms and years.

    The engine derives the policy from observed data; locating that data is a
    layout concern, so it is resolved here.
    """
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

    The year is read off ``report_date`` with the same plausibility clip the
    unfiltered bound has always used. The narrowing is optional because the two
    callers want different things: automatic era bands want the years a
    *selection* can reach, while the fallback for a selection that reaches
    nothing wants every year the catalog holds.
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
    if date_selection:
        clauses.append(date_selection_sql(date_selection))
    return f"""
        SELECT
            MIN(CAST(substring(report_date, 1, 4) AS INTEGER)),
            MAX(CAST(substring(report_date, 1, 4) AS INTEGER))
        FROM {relation}
        WHERE {" AND ".join(clauses)}
    """


def _current_year() -> int:
    import datetime

    return datetime.datetime.now(datetime.UTC).year


def _target_relation(paths: FilingCatalogPaths, catalog_id: str) -> str | None:
    """Return the catalog's targets as one relation, or ``None`` when absent."""
    target_files = sorted(paths.snapshot_targets_dir(catalog_id).glob("part-*.parquet"))
    if not target_files:
        return None
    file_list = ", ".join(sql_literal(str(path)) for path in target_files)
    return f"read_parquet([{file_list}])"


def catalog_year_bounds(paths: FilingCatalogPaths, catalog_id: str) -> tuple[int, int]:
    """Return the observed report-year range of a catalog, clipped to EDGAR.

    Named because automatic era bands need it as a fallback: a selection that
    matches no dated row still has to publish bands, and the honest ones then
    come from every year the catalog holds.
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
    """Return the report-year range a selection can reach, or ``None`` if empty.

    ``None`` rather than a synthetic range, because "this selection matches no
    dated row" is a fact the caller must handle differently from "the catalog is
    narrow": the first means derive bands from something else, the second means
    these are the bands.
    """
    relation = _target_relation(paths, catalog_id)
    if relation is None:
        return None
    query = _year_bounds_query(relation, forms=forms, date_selection=date_selection)
    if date_selection:
        query = query.replace(
            f"FROM {relation}", f"FROM {parsed_date_relation(relation, 'report_date')}"
        )
    with connect() as con:
        row = con.execute(query).fetchone()
    if not row or row[0] is None or row[1] is None:
        return None
    return int(row[0]), int(row[1])


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
