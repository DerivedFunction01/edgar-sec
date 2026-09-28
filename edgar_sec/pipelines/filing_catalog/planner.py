"""Deterministic target planning for the filing catalog.

Deterministic planning is a fast, zero-heuristic slice of a materialized
catalog. It deliberately supports exactly four filters -- ``forms``,
``amendment``, ``document_suffixes``, and ``limit`` -- and refuses to reason
about dates, eras, or cohort balance, which belong to the Stage B selection
policy. Passing a date argument raises ``TypeError`` rather than being ignored.

Two corrections against v1:

* the ``amendment`` policy is actually applied. v1 validated the value and
  recorded it in ``plan.json`` but never filtered on it, so ``--amendment
  original`` silently behaved like ``both``.
* the policy-only parameters (``selection_policy_path``, ``seed_cik_path``,
  ``parent_plan_dir``, ``target_units``) are absent from this signature. They
  reappear with the Stage B selection engine and plan expansion.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.progress import ProgressCallback, emit_progress
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.duckdb_catalog import copy_query_to_parquet, sql_literal
from edgar_sec.infra.storage.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.filing_catalog.filters import (
    AMENDMENT_POLICIES,
    DEFAULT_AMENDMENT,
    DEFAULT_DOCUMENT_SUFFIXES,
    amendment_sql,
    normalize_suffixes,
    suffix_sql,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    CURRENT_ALIAS,
    LOCATOR_GROUPS_NAME,
    PLAN_TARGETS_DIR_NAME,
    FilingCatalogPaths,
    form_partition_name,
    resolve_filing_catalog_paths,
    safe_identifier,
)
from edgar_sec.pipelines.filing_catalog.publication import (
    TARGET_PLAN_SCHEMA_VERSION,
    PlanConflictError,
    plan_identity,
    reuse_existing_plan,
    staged_plan_bundle,
    write_plan_documents,
)

SCOPE_DETERMINISTIC = "deterministic"

# Characters permitted in a form filter. '/' is allowed because amendment forms
# are written that way ("8-K/A") and are escaped at partition time.
_ID_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
_FORM_SEPARATOR = "/"


def _validate_forms(forms: tuple[str, ...]) -> tuple[str, ...]:
    for form in forms:
        if not form or not form.strip():
            raise ValueError("form filters must be non-empty")
        if not set(form) <= _ID_SAFE | {_FORM_SEPARATOR}:
            raise ValueError(f"unsafe form filter: {form!r}")
    return tuple(dict.fromkeys(forms))


def _locator_groups_query(source_sql: str) -> str:
    """Stage A locator projection: exactly one row per document locator.

    This is the narrow eight-column shape. Stage B widens it with the feature
    dimensions (form_family, era, size_band, ...); see phase_2.md 3.4. A
    consumer must not assume the wider set in Stage A.

    Grouping is on ``document_locator_key`` alone, with the representative
    columns chosen by ``arg_min`` over a total order. v1 selected ``DISTINCT``
    over *all* columns including ``source_cik``, so two co-filers sharing one
    locator produced two rows and ``unique_locators_count`` over-counted -- which
    is precisely the multiplicity Stage B selection must not inherit. The
    ordering key is total, so the representative is deterministic.

    ``source_sql`` is any relation expression. A plan that matched nothing still
    needs a schema-correct zero-row locator file, otherwise its own bundle fails
    :func:`plan_bundle_complete` and cannot be reused; callers pass a
    ``WHERE false`` predicate over the catalog view in that case.
    """
    order = (
        "source_cik || '|' || accession || '|' || document_path || '|' || "
        "coalesce(primary_document, '')"
    )
    return f"""
    SELECT
        document_locator_key,
        arg_min(form, {order}) AS form,
        arg_min(source_cik, {order}) AS representative_cik,
        arg_min(accession, {order}) AS representative_accession,
        arg_min(primary_document, {order}) AS primary_document,
        arg_min(document_path, {order}) AS document_path,
        arg_min(archive_url, {order}) AS archive_url,
        arg_min(document_path_source, {order}) AS document_path_source
    FROM {source_sql}
    GROUP BY document_locator_key
    ORDER BY document_locator_key
    """


def _catalog_target_files(paths: FilingCatalogPaths, catalog_id: str) -> list[Path]:
    targets_dir = paths.snapshot_targets_dir(catalog_id)
    if not targets_dir.is_dir():
        raise PlanConflictError(f"catalog has no published targets: {targets_dir}")
    files = sorted(targets_dir.glob("part-*.parquet"))
    if not files:
        raise PlanConflictError(f"catalog target directory is empty: {targets_dir}")
    return files


def resolve_catalog_reference(paths: FilingCatalogPaths, catalog: str) -> str:
    """Resolve a catalog reference to a concrete catalog id.

    Accepts a literal id or the ``current`` alias, which the pointer resolves.
    A literal id is validated as a path segment, so a caller-supplied string
    can never escape the snapshots tree.
    """
    if catalog == CURRENT_ALIAS:
        from edgar_sec.pipelines.filing_catalog.discovery import current_catalog_id

        resolved = current_catalog_id(paths)
        if resolved is None:
            raise PlanConflictError(
                "no catalog is published as current; pass an explicit catalog id"
            )
        return resolved
    return safe_identifier(catalog)


def plan(
    catalog: str,
    output_root: str | Path | None = None,
    *,
    forms: tuple[str, ...] | None = None,
    amendment: str | None = None,
    document_suffixes: tuple[str, ...] | None = None,
    limit: int | None = None,
    progress: ProgressCallback = None,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
) -> dict[str, Any]:
    """Publish one immutable deterministic target-plan bundle.

    The bundle partitions the catalog's targets by form, records the request
    that produced it, and publishes atomically. Returns the plan document.
    """
    if not catalog:
        raise ValueError("catalog is required")
    if amendment is None:
        amendment = DEFAULT_AMENDMENT
    if amendment not in AMENDMENT_POLICIES:
        raise ValueError(
            f"amendment must be one of {', '.join(AMENDMENT_POLICIES)}; "
            f"got {amendment!r}"
        )
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    suffixes = normalize_suffixes(
        document_suffixes
        if document_suffixes is not None
        else DEFAULT_DOCUMENT_SUFFIXES
    )
    requested_forms = _validate_forms(tuple(forms or ()))

    paths = (
        resolve_filing_catalog_paths(output_root)
        if output_root is not None
        else resolve_filing_catalog_paths()
    )
    catalog = resolve_catalog_reference(paths, catalog)
    source_files = _catalog_target_files(paths, catalog)

    request = {
        "catalog_id": catalog,
        "scope": SCOPE_DETERMINISTIC,
        "forms": list(requested_forms),
        "amendment": amendment,
        "document_suffixes": list(suffixes),
        "limit": limit,
        "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
    }
    plan_id = plan_identity(request)
    final_dir = paths.plan_dir(plan_id)

    existing = reuse_existing_plan(final_dir, plan_id, SCOPE_DETERMINISTIC)
    if existing is not None:
        emit_progress(
            progress,
            {"type": "merge_stage", "stage": "reuse_plan", "plan_id": plan_id},
        )
        return existing

    emit_progress(
        progress,
        {
            "type": "merge_stage",
            "stage": "plan",
            "plan_id": plan_id,
            "catalog": catalog,
        },
    )

    with connect() as con:
        view = "catalog_targets"
        file_list = ", ".join(sql_literal(str(path)) for path in source_files)
        con.execute(
            f"CREATE OR REPLACE TEMP VIEW {view} AS "
            f"SELECT * FROM read_parquet([{file_list}]) WHERE form IS NOT NULL"
        )

        # The amendment and suffix filters are part of which partitions exist at
        # all, so they are applied when discovering forms. v1 listed every form
        # present in the catalog and then wrote empty partitions for the ones
        # the filters removed.
        shared_where: list[str] = []
        if requested_forms:
            form_list = ", ".join(sql_literal(form) for form in requested_forms)
            shared_where.append(f"form IN ({form_list})")
        amendment_clause = amendment_sql(amendment)
        if amendment_clause != "TRUE":
            shared_where.append(amendment_clause)
        suffix_clause = suffix_sql("document_path", suffixes)
        if suffix_clause != "TRUE":
            shared_where.append(f"({suffix_clause})")

        discovery = " AND ".join(shared_where) if shared_where else "TRUE"
        available = [
            str(row[0])
            for row in con.execute(
                f"SELECT DISTINCT form FROM {view} WHERE {discovery} ORDER BY form"
            ).fetchall()
        ]

        counts: dict[str, int] = {}
        total_rows = 0
        with staged_plan_bundle(final_dir, plan_id) as staging:
            targets_root = staging / PLAN_TARGETS_DIR_NAME
            # Created even when no form matches, so a zero-row plan is still
            # a structurally complete, reusable bundle.
            targets_root.mkdir(parents=True, exist_ok=True)
            written: list[Path] = []
            for form_name in available:
                partition = form_partition_name(form_name)
                destination = targets_root / f"form={partition}" / "data.parquet"
                where = [*shared_where, f"form = {sql_literal(form_name)}"]
                query = (
                    f"SELECT * FROM {view} WHERE {' AND '.join(where)} "
                    f"ORDER BY document_locator_key, occurrence_id"
                )
                if limit is not None:
                    query = f"SELECT * FROM ({query}) LIMIT {int(limit)}"
                written.append(destination)
                counts[form_name] = copy_query_to_parquet(
                    con, query, destination, row_group_size
                )
                total_rows += counts[form_name]
                emit_progress(
                    progress,
                    {
                        "type": "merge_stage",
                        "stage": f"targets:{form_name}",
                        "rows": counts[form_name],
                    },
                )

            # Always written, even at zero rows, so every published bundle holds
            # the full REQUIRED_PLAN_FILES set and stays reusable.
            if written:
                file_list = ", ".join(sql_literal(str(path)) for path in written)
                locator_source = f"read_parquet([{file_list}])"
            else:
                locator_source = f"(SELECT * FROM {view} WHERE false)"
            locator_count = copy_query_to_parquet(
                con,
                _locator_groups_query(locator_source),
                staging / LOCATOR_GROUPS_NAME,
                row_group_size,
            )

            selection_report = {
                "scope": SCOPE_DETERMINISTIC,
                "catalog_id": catalog,
                "plan_id": plan_id,
                "active_targets_count": total_rows,
                "unique_locators_count": locator_count,
                "counts": counts,
            }
            plan_meta = {
                "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
                "plan_id": plan_id,
                "catalog_id": catalog,
                "scope": SCOPE_DETERMINISTIC,
                "forms": list(requested_forms),
                "amendment": amendment,
                "document_suffixes": list(suffixes),
                "limit": limit,
                "counts": counts,
                "selected_rows": total_rows,
                "active_targets_count": total_rows,
                "unique_locators_count": locator_count,
                "request_fingerprint": hashlib.sha256(
                    json.dumps(request, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            }
            write_plan_documents(staging, plan_meta, selection_report)

    return plan_meta


__all__ = [
    "CURRENT_ALIAS",
    "SCOPE_DETERMINISTIC",
    "plan",
    "resolve_catalog_reference",
]
