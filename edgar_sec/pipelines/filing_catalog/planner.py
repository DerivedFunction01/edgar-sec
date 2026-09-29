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

from edgar_sec.domain.filing_catalog.filters import (
    AMENDMENT_POLICIES,
    DEFAULT_AMENDMENT,
    DEFAULT_DOCUMENT_SUFFIXES,
    normalize_suffixes,
)
from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_POLICY_COLUMNS,
    SCOPE_DETERMINISTIC,
    SCOPE_POLICY,
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
    resolve_seed_filers,
    write_seed_filers_csv,
)
from edgar_sec.engine.selection.selector import DeficitSelector
from edgar_sec.foundation.runtime.progress import ProgressCallback, emit_progress
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.duckdb_catalog import (
    amendment_sql,
    copy_query_to_parquet,
    sql_literal,
    suffix_sql,
)
from edgar_sec.infra.storage.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.filing_catalog.discovery import resolve_catalog_reference
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
            plan_meta = write_plan_documents(staging, plan_meta, selection_report)

    return plan_meta


def _policy_locator_groups_query(locator_source: str) -> str:
    """Stage B locator projection: the 18-column policy schema.

    Same one-row-per-document guarantee as the Stage A variant, widened with the
    stratification dimensions. A consumer that audits a published sample --
    "is this actually era-balanced, or is it all one SIC band?" -- needs those
    values in the plan itself, not only in the transient feature snapshot.
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
    """Predict, before selection ran, whether the corpus could have met the quotas.

    Advisory only. A fresh policy plan publishes whatever the corpus could
    supply and records the shortfall in ``underfilled_floors``; this report never
    changes that, because a feasibility prediction is weaker evidence than a
    completed selection. Two things make it a prediction rather than a promise:

    * The per-dimension counts are independent. They do not subtract competition
      between floors, the family cap, or the seeds, so a set of individually
      feasible floors can still underfill together.
    * A floor can be satisfiable and still be skipped once a cap or an earlier
      phase has claimed the candidates.

    It is still the cheapest way to turn "this policy produced an empty plan" into
    "this policy asked for 40 filings in an era the corpus does not have".
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
        # reason to fail a plan that selection has already completed.
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
    """Load the selected locator keys into a temp table for the bundle writes.

    One temp table rather than an interpolated list: an expanded plan carries
    thousands of keys, and a list that long would be re-parsed per query.
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

    The scope counterpart to :func:`plan`. Where deterministic planning slices a
    catalog on four filters, this runs the Stage B selection engine against a
    declared quota profile and publishes the result: quota-balanced locators, the
    18-column locator projection, a reserve pool, and the policy that produced
    it, all recorded in ``plan.json``.

    The bundle is written from SQL against the feature snapshot rather than from
    the selector's in-memory candidate list, so publishing a large expanded plan
    does not scale with the plan size in the Python heap.
    """
    if not policy.forms:
        raise ValueError("policy must configure at least one form")

    paths = (
        resolve_filing_catalog_paths(output_root)
        if output_root is not None
        else resolve_filing_catalog_paths()
    )
    catalog = resolve_catalog_reference(paths, catalog)
    # Guard, not an input: the builder re-globs the same directory, but this
    # raises "catalog has no published targets" instead of letting the failure
    # surface as a missing-parts error from inside feature building.
    _catalog_target_files(paths, catalog)

    # Normalized once, then carried everywhere: the feature snapshot, the
    # selector, the published sidecar, and the plan identity. Reading the seed
    # manifest per consumer is what let a plan and the features behind it
    # disagree about which registrants were mandatory.
    pinned_seed = (
        dict(seed_filers) if seed_filers is not None else resolve_seed_filers(policy)
    )
    seed_fingerprint = compute_seed_fingerprint(pinned_seed)
    request = {
        "catalog_id": catalog,
        "scope": SCOPE_POLICY,
        "policy_fingerprint": policy.policy_fingerprint,
        "seed_fingerprint": seed_fingerprint,
        "target_units": policy.requested_units(),
        "level": policy.level,
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
        seed_filers=pinned_seed,
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
                # filters rows, and `SELECT *` would project the join key a
                # second time, publishing a `document_locator_key_1` column
                # alongside the real one. The published partition must keep
                # exactly the feature snapshot's occurrence schema.
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
            "amendment": policy.amendment,
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
