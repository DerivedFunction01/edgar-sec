"""Deterministic target planning for the filing catalog.
``dates`` is a *selection*, not a year list: absolute intervals and recurring periods
in the grammar ``domain.filing_catalog.filters`` owns, applied to ``report_date``.
A nonempty selection excludes rows with a missing ``report_date``. Forms are exact.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.filters import (
    DEFAULT_DOCUMENT_SUFFIXES,
    date_selection_to_json,
    format_date_selection,
    normalize_suffixes,
    parse_date_selection,
)
from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_POLICY_COLUMNS,
    SCOPE_DETERMINISTIC,
    SCOPE_POLICY,
    TARGET_COLUMNS,
)
from edgar_sec.engine.selection.features import (
    FeatureSnapshotBuilder,
    SnapshotPaths,
)
from edgar_sec.engine.selection.inventory import (
    InventoryStatistics,
    OccurrenceOnlyDimensionError,
    UnknownDimensionError,
)
from edgar_sec.engine.selection.policy import (
    SeedFiler,
    SelectionPolicy,
    compute_seed_fingerprint,
    era_bands_for_range,
    resolve_seed_filers,
    write_seed_filers_csv,
)
from edgar_sec.engine.selection.predicates import (
    date_projection_sql,
    date_selection_sql,
    suffix_sql,
)
from edgar_sec.engine.selection.selector import DeficitSelector
from edgar_sec.foundation.runtime.progress import ProgressCallback, emit_progress
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
)
from edgar_sec.infra.storage.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.filing_catalog.discovery import (
    catalog_year_bounds,
    eligible_year_bounds,
    resolve_catalog_reference,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_NAME,
    PLAN_TARGETS_DIR_NAME,
    RESERVE_TARGETS_NAME,
    SEED_FILERS_NAME,
    FilingCatalogPaths,
    form_partition_name,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.publication import (
    TARGET_PLAN_SCHEMA_VERSION,
    PlanConflictError,
    plan_identity,
    reuse_existing_plan,
    staged_plan_bundle,
    write_plan_documents,
)

# Characters permitted in a form filter. '/' is allowed because amendment forms
# are written that way ("8-K/A") and are escaped at partition time.
_KEY_INSERT_BATCH = 5_000
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
    """Deterministic-scope locator projection: one row per locator.
    Grouping on ``document_locator_key`` alone collapses co-filers, so
    ``unique_locators_count`` counts documents not claims.
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


def plan(
    catalog: str,
    output_root: str | Path | None = None,
    *,
    forms: tuple[str, ...] | None = None,
    document_suffixes: tuple[str, ...] | None = None,
    dates: str | None = None,
    limit: int | None = None,
    progress: ProgressCallback = None,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
) -> dict[str, Any]:
    """Publish one immutable deterministic target-plan bundle.
    Normalized date clauses, not the caller's spelling, enter the request, so two
    spellings of one selection resolve to the same plan.
    """
    if not catalog:
        raise ValueError("catalog is required")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    suffixes = normalize_suffixes(
        document_suffixes
        if document_suffixes is not None
        else DEFAULT_DOCUMENT_SUFFIXES
    )
    requested_forms = _validate_forms(tuple(forms or ()))
    date_selection = parse_date_selection(dates or "")

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
        "document_suffixes": list(suffixes),
        "date_selection": date_selection_to_json(date_selection),
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

        # A date selection filters on a parsed DATE, projected once here rather
        # than per reference in the predicate.
        source = view
        if date_selection:
            source = "catalog_dated"
            con.execute(
                f"CREATE OR REPLACE TEMP VIEW {source} AS SELECT *, "
                f"{date_projection_sql('report_date')} FROM {view}"
            )

        # Form discovery runs the same predicates the partition writes do, so a
        # form the filters remove is never discovered and no empty partition is
        # published for it.
        shared_where: list[str] = []
        if requested_forms:
            form_list = ", ".join(sql_literal(form) for form in requested_forms)
            shared_where.append(f"form IN ({form_list})")
        suffix_clause = suffix_sql("document_path", suffixes)
        if suffix_clause != "TRUE":
            shared_where.append(f"({suffix_clause})")
        date_clause = date_selection_sql(date_selection)
        if date_clause != "TRUE":
            shared_where.append(date_clause)

        discovery = " AND ".join(shared_where) if shared_where else "TRUE"
        available = [
            str(row[0])
            for row in con.execute(
                f"SELECT DISTINCT form FROM {source} WHERE {discovery} ORDER BY form"
            ).fetchall()
        ]

        # A shard is schema-checked against TARGET_COLUMNS, so partitions project the
        # published columns by name rather than the dated view's shape.
        target_columns = ", ".join(TARGET_COLUMNS)

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
                    f"SELECT {target_columns} FROM {source} "
                    f"WHERE {' AND '.join(where)} "
                    f"ORDER BY document_locator_key, occurrence_id"
                )
                if limit is not None:
                    query = f"SELECT {target_columns} FROM ({query}) LIMIT {int(limit)}"
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

            # Written even at zero rows, so every published bundle holds the full
            # REQUIRED_PLAN_FILES set and stays reusable.
            if written:
                file_list = ", ".join(sql_literal(str(path)) for path in written)
                locator_source = f"read_parquet([{file_list}])"
            else:
                locator_source = f"(SELECT * FROM {source} WHERE false)"
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
                "date_selection": date_selection_to_json(date_selection),
                "date_selection_text": format_date_selection(date_selection),
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
                "document_suffixes": list(suffixes),
                "date_selection": date_selection_to_json(date_selection),
                "date_selection_text": format_date_selection(date_selection),
                "limit": limit,
                "counts": counts,
                "selected_rows": total_rows,
                "active_targets_count": total_rows,
                "unique_locators_count": locator_count,
                "request_fingerprint": hashlib.sha256(
                    json.dumps(request, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            }
            plan_meta = write_plan_documents(staging, plan_meta, selection_report)

    return plan_meta


def _policy_locator_groups_query(locator_source: str) -> str:
    """Policy-scope locator projection: the policy locator schema.
    Widened with the stratification dimensions: auditing a sample needs them in the
    plan, not only in the feature snapshot.
    """
    projection = ", ".join(f"l.{column}" for column in LOCATOR_POLICY_COLUMNS)
    return f"""
    SELECT {projection}
    FROM {locator_source}
    ORDER BY document_locator_key
    """


def _inventory_feasibility(
    snapshot: SnapshotPaths, policy: SelectionPolicy
) -> dict[str, Any]:
    """Predict, before selection ran, whether quotas were meetable.
    Advisory only; a completed selection is stronger evidence. Per-dimension counts are
    independent of competition between floors, caps, and seeds.
    """
    if not policy.floors and not policy.composites:
        return {"checked": False, "reason": "policy declares no floors or composites"}
    statistics = InventoryStatistics(snapshot.snapshot_dir)
    try:
        floors = (
            statistics.check_floor_feasibility(policy.floors) if policy.floors else {}
        )
        composites = (
            statistics.check_composite_feasibility(policy.composites)
            if policy.composites
            else []
        )
    except (UnknownDimensionError, OccurrenceOnlyDimensionError, OSError) as error:
        # A policy the inventory cannot evaluate is a policy problem, not a
        # reason to fail a plan selection has already completed.
        return {"checked": False, "reason": f"inventory unavailable: {error}"}
    return {
        "checked": True,
        "floors": floors,
        "composites": composites,
        "infeasible_floors": sorted(
            value
            for dimension in floors.values()
            for value, entry in dimension.items()
            if not entry["feasible"]
        ),
        "infeasible_composites": [
            entry["filters"] for entry in composites if not entry["feasible"]
        ],
    }


def _register_selected_keys(con: object, keys: list[str]) -> None:
    """Load the selected locator keys into a temp table.
    A temp table, not an interpolated list: a plan carries thousands of keys and a list
    that long is re-parsed per query.
    """
    con.execute(
        "CREATE OR REPLACE TEMP TABLE selected_locator_keys "
        "(document_locator_key VARCHAR)"
    )
    for start in range(0, len(keys), _KEY_INSERT_BATCH):
        chunk = [[key] for key in keys[start : start + _KEY_INSERT_BATCH]]
        con.executemany("INSERT INTO selected_locator_keys VALUES (?)", chunk)


def _register_reserve_keys(con: object, keys: list[str]) -> None:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE reserve_locator_keys "
        "(document_locator_key VARCHAR)"
    )
    for start in range(0, len(keys), _KEY_INSERT_BATCH):
        chunk = [[key] for key in keys[start : start + _KEY_INSERT_BATCH]]
        con.executemany("INSERT INTO reserve_locator_keys VALUES (?)", chunk)


def _resolve_era_bands(
    paths: FilingCatalogPaths, catalog: str, policy: SelectionPolicy
) -> SelectionPolicy:
    """Return the policy carrying the era bands selection will use.
    Resolved before the feature build, since era is baked into the snapshot: deriving
    later would describe a stratification the locators were not chosen under.
    """
    if not policy.derives_era_bands:
        return policy
    bounds = eligible_year_bounds(
        paths, catalog, forms=policy.forms, date_selection=policy.date_selection_clauses
    )
    if bounds is None:
        bounds = catalog_year_bounds(paths, catalog)
    return policy.with_era_bands(era_bands_for_range(*bounds))


def plan_policy(
    catalog: str,
    policy: SelectionPolicy,
    output_root: str | Path | None = None,
    *,
    seed_filers: dict[str, SeedFiler] | None = None,
    parent_active_keys: list[str] | None = None,
    progress: ProgressCallback = None,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
) -> dict[str, Any]:
    """Publish one immutable policy-driven target-plan bundle.
    Written from SQL against the feature snapshot, so publishing does not scale with
    plan size in the Python heap.
    """
    if not policy.forms:
        raise ValueError("policy must configure at least one form")

    paths = (
        resolve_filing_catalog_paths(output_root)
        if output_root is not None
        else resolve_filing_catalog_paths()
    )
    catalog = resolve_catalog_reference(paths, catalog)
    # A guard, not an input: it reports "no published targets" rather than
    # letting the builder surface it as a missing-parts error.
    _catalog_target_files(paths, catalog)

    # Resolved before the request is hashed, so the plan id names the bands its
    # locators will actually be chosen under.
    policy = _resolve_era_bands(paths, catalog, policy)

    # Pinned once, then carried everywhere: reading the seed manifest per
    # consumer is what let a plan and its features disagree about which
    # registrants were mandatory.
    pinned_seed = (
        dict(seed_filers) if seed_filers is not None else resolve_seed_filers(policy)
    )
    seed_fingerprint = compute_seed_fingerprint(pinned_seed)
    # ``target_units`` and ``level`` stay out: ``policy_fingerprint`` already
    # covers both, and restating them gave the identity two encodings of one fact.
    request = {
        "catalog_id": catalog,
        "scope": SCOPE_POLICY,
        "policy_fingerprint": policy.policy_fingerprint,
        "seed_fingerprint": seed_fingerprint,
        "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
    }
    plan_id = plan_identity(request)
    final_dir = paths.plan_dir(plan_id)

    existing = reuse_existing_plan(final_dir, plan_id, SCOPE_POLICY)
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
            "stage": "policy_plan",
            "plan_id": plan_id,
            "catalog": catalog,
        },
    )

    builder = FeatureSnapshotBuilder(
        target_root=paths.snapshot_targets_dir(catalog),
        profile_path=paths.snapshot_profiles_file(catalog),
        output_root=paths.catalog_root,
        policy=policy,
        row_group_size=row_group_size,
    )
    snapshot = builder.build()
    emit_progress(
        progress,
        {
            "type": "merge_stage",
            "stage": "features",
            "snapshot": snapshot.snapshot_dir.name,
        },
    )

    selector = DeficitSelector(snapshot.snapshot_dir, policy, seed_filers=pinned_seed)
    selection = selector.select(parent_active_keys=parent_active_keys)

    counts: dict[str, int] = {}
    total_rows = 0
    with staged_plan_bundle(final_dir, plan_id) as staging:
        write_seed_filers_csv(staging / SEED_FILERS_NAME, pinned_seed)
        targets_root = staging / PLAN_TARGETS_DIR_NAME
        targets_root.mkdir(parents=True, exist_ok=True)
        with connect() as con:
            _register_selected_keys(con, selection.active_locators)
            locator_source = (
                "read_parquet("
                f"{sql_literal(str(snapshot.locator_features))}) l "
                "JOIN selected_locator_keys s "
                "ON l.document_locator_key = s.document_locator_key"
            )
            occurrence_source = (
                "read_parquet("
                f"{sql_literal(str(snapshot.occurrence_features))}) o "
                "JOIN selected_locator_keys s "
                "ON o.document_locator_key = s.document_locator_key"
            )

            selected_forms = [
                str(row[0])
                for row in con.execute(
                    f"SELECT DISTINCT form FROM ({occurrence_source}) ORDER BY form"
                ).fetchall()
            ]
            for form_name in selected_forms:
                destination = (
                    targets_root
                    / f"form={form_partition_name(form_name)}"
                    / "data.parquet"
                )
                # `o.*`, not `*`: the relation is a join whose second input only
                # filters rows, so `SELECT *` would publish a
                # `document_locator_key_1` column beside the real one.
                query = (
                    f"SELECT o.* FROM ({occurrence_source}) "
                    f"WHERE form = {sql_literal(form_name)} "
                    "ORDER BY o.document_locator_key, o.occurrence_id"
                )
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

            locator_count = copy_query_to_parquet(
                con,
                _policy_locator_groups_query(locator_source),
                staging / LOCATOR_GROUPS_NAME,
                row_group_size,
            )

            if selection.reserve_locators:
                _register_reserve_keys(con, selection.reserve_locators)
                copy_query_to_parquet(
                    con,
                    "SELECT l.* FROM "
                    f"read_parquet({sql_literal(str(snapshot.locator_features))}) l "
                    "JOIN reserve_locator_keys r "
                    "ON l.document_locator_key = r.document_locator_key "
                    "ORDER BY l.document_locator_key",
                    staging / RESERVE_TARGETS_NAME,
                    row_group_size,
                )

        selection_report = {
            "scope": SCOPE_POLICY,
            "catalog_id": catalog,
            "plan_id": plan_id,
            "active_targets_count": total_rows,
            "unique_locators_count": locator_count,
            "reserve_count": len(selection.reserve_locators),
            "counts": counts,
            "inventory_feasibility": _inventory_feasibility(snapshot, policy),
            **{
                k: v
                for k, v in selection.report.items()
                if k != "coverage_distributions"
            },
        }
        plan_meta = {
            "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "catalog_id": catalog,
            "scope": SCOPE_POLICY,
            "policy_corpus": policy.corpus_id,
            "policy_fingerprint": policy.policy_fingerprint,
            "seed_fingerprint": seed_fingerprint,
            "seed_filer_count": len(pinned_seed),
            "level": policy.level,
            "target_units": policy.requested_units(),
            "parent_plan_id": policy.parent_plan_id,
            "forms": list(policy.forms),
            "document_suffixes": list(policy.document_suffixes),
            "counts": counts,
            "selected_rows": total_rows,
            "active_targets_count": total_rows,
            "unique_locators_count": locator_count,
            "reserve_count": len(selection.reserve_locators),
            "underfilled_floors": selection.report["underfilled_floors"],
            "selection_policy": policy.to_dict(),
            "request_fingerprint": hashlib.sha256(
                json.dumps(request, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }
        plan_meta = write_plan_documents(staging, plan_meta, selection_report)

    return plan_meta


__all__ = [
    "SCOPE_DETERMINISTIC",
    "SCOPE_POLICY",
    "plan",
    "plan_policy",
]
