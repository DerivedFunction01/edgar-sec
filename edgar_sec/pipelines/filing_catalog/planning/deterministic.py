"""Deterministic target planning for the filing catalog.
``dates`` is a selection grammar applied to ``report_date``.
A nonempty selection excludes rows with a missing ``report_date``.
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
from edgar_sec.domain.filing_catalog.options import PlanFilterOptions
from edgar_sec.domain.filing_catalog.schemas import (
    SCOPE_DETERMINISTIC,
    TARGET_COLUMNS,
)
from edgar_sec.engine.selection.predicates import (
    date_projection_sql,
    date_selection_sql,
    suffix_sql,
)
from edgar_sec.foundation.runtime.paths import DATA_FILE_NAME
from edgar_sec.foundation.runtime.progress import ProgressCallback, emit_progress
from edgar_sec.foundation.runtime.settings.parquet import resolve_row_group_size
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
)
from edgar_sec.pipelines.filing_catalog.accessions import (
    select_accession_groups,
    selected_accession_counts,
    validate_limit_options,
)
from edgar_sec.pipelines.filing_catalog.discovery import (
    resolve_catalog_reference,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_FILE,
    PLAN_TARGETS_DIR,
    form_partition_directory,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.publication import (
    TARGET_PLAN_SCHEMA_VERSION,
    plan_identity,
    reuse_existing_plan,
    staged_plan_bundle,
    write_plan_documents,
)
from .shared import (
    catalog_target_files,
    resolve_cohort,
    validate_forms,
)


def _locator_groups_query(source_sql: str) -> str:
    """Deterministic-scope locator projection: one row per locator."""
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


def plan(
    catalog: str,
    output_root: str | Path | None = None,
    *,
    filters: PlanFilterOptions | None = None,
    forms: tuple[str, ...] | None = None,
    document_suffixes: tuple[str, ...] | None = None,
    dates: str | None = None,
    limit: int | None = None,
    accession_limit: int | None = None,
    min_exhibit_like: int | None = None,
    cohort: str | None = None,
    xbrl_only: bool = False,
    progress: ProgressCallback = None,
    row_group_size: int | None = None,
) -> dict[str, Any]:
    """Publish one immutable deterministic target-plan bundle."""
    row_group_size = resolve_row_group_size(row_group_size)
    if not catalog:
        raise ValueError("catalog is required")

    effective_filters = filters or PlanFilterOptions(
        forms=forms or (),
        document_suffixes=document_suffixes,
        dates=dates,
        limit=limit,
        accession_limit=accession_limit,
        min_exhibit_like=min_exhibit_like,
        cohort=cohort,
        xbrl_only=xbrl_only,
    )
    validate_limit_options(
        effective_filters.limit,
        effective_filters.accession_limit,
        effective_filters.min_exhibit_like,
    )

    suffixes = normalize_suffixes(
        effective_filters.document_suffixes
        if effective_filters.document_suffixes is not None
        else DEFAULT_DOCUMENT_SUFFIXES
    )
    requested_forms = validate_forms(tuple(effective_filters.forms or ()))
    date_selection = parse_date_selection(effective_filters.dates or "")

    paths = (
        resolve_filing_catalog_paths(output_root)
        if output_root is not None
        else resolve_filing_catalog_paths()
    )
    catalog = resolve_catalog_reference(paths, catalog)
    source_files = catalog_target_files(paths, catalog)
    cohort_input = resolve_cohort(paths.artifacts_root, effective_filters.cohort)

    request = {
        "catalog_id": catalog,
        "row_group_size": row_group_size,
        "scope": SCOPE_DETERMINISTIC,
        "forms": list(requested_forms),
        "document_suffixes": list(suffixes),
        "date_selection": date_selection_to_json(date_selection),
        "limit": effective_filters.limit,
        "accession_limit": effective_filters.accession_limit,
        "min_exhibit_like": effective_filters.min_exhibit_like,
        "xbrl_only": bool(effective_filters.xbrl_only),
        "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
    }
    if cohort_input is not None:
        cohort_record, _ = cohort_input
        request["cohort_id"] = cohort_record.cohort_id
        request["cohort_dataset_sha256"] = cohort_record.dataset_sha256
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
        source = view
        if cohort_input is not None:
            _, cohort_dataset = cohort_input
            con.execute("CREATE TEMP TABLE cohort_ciks (cohort_cik BIGINT)")
            con.execute(
                "INSERT INTO cohort_ciks "
                "SELECT try_cast(cik_padded AS BIGINT) "
                "FROM read_parquet(?)",
                [str(cohort_dataset)],
            )
            source = "cohort_targets"
            con.execute(
                "CREATE OR REPLACE TEMP VIEW cohort_targets AS "
                "SELECT target.* FROM catalog_targets target "
                "SEMI JOIN cohort_ciks cohort "
                "ON try_cast(target.source_cik AS BIGINT) = cohort.cohort_cik"
            )

        if date_selection:
            date_source = source
            source = "catalog_dated"
            con.execute(
                f"CREATE OR REPLACE TEMP VIEW {source} AS SELECT *, "
                f"{date_projection_sql('report_date')} FROM {date_source}"
            )

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
        if effective_filters.xbrl_only:
            shared_where.append("(is_xbrl = TRUE OR is_inline_xbrl = TRUE)")

        discovery = " AND ".join(shared_where) if shared_where else "TRUE"

        selected_accessions_count = select_accession_groups(
            con,
            source,
            discovery,
            effective_filters.accession_limit,
            effective_filters.min_exhibit_like,
        )
        if effective_filters.accession_limit is not None:
            shared_where.append(
                "accession IN (SELECT accession FROM selected_accessions)"
            )
            discovery = " AND ".join(shared_where) if shared_where else "TRUE"

        available = con.execute(
            f"SELECT DISTINCT form FROM {source} WHERE {discovery} ORDER BY form"
        ).to_arrow_reader(batch_size=resolve_read_batch_size())

        target_columns = ", ".join(TARGET_COLUMNS)

        counts: dict[str, int] = {}
        total_rows = 0
        with staged_plan_bundle(final_dir, plan_id) as staging:
            targets_root = staging / PLAN_TARGETS_DIR
            targets_root.mkdir(parents=True, exist_ok=True)
            written: list[Path] = []
            for form_batch in available:
                form_values = form_batch.column(0)
                for row_index in range(form_batch.num_rows):
                    form_name = str(form_values[row_index].as_py())
                    destination = (
                        targets_root
                        / form_partition_directory(form_name)
                        / DATA_FILE_NAME
                    )
                    where = [*shared_where, f"form = {sql_literal(form_name)}"]
                    query = (
                        f"SELECT {target_columns} FROM {source} "
                        f"WHERE {' AND '.join(where)} "
                        f"ORDER BY document_locator_key, occurrence_id"
                    )
                    if effective_filters.limit is not None:
                        query = f"SELECT {target_columns} FROM ({query}) LIMIT {int(effective_filters.limit)}"
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

            if written:
                file_list = ", ".join(sql_literal(str(path)) for path in written)
                locator_source = f"read_parquet([{file_list}])"
            else:
                locator_source = f"(SELECT * FROM {source} WHERE false)"
            (
                selected_accessions_count,
                selected_exhibit_like_count,
            ) = selected_accession_counts(con, locator_source)
            locator_count = copy_query_to_parquet(
                con,
                _locator_groups_query(locator_source),
                staging / LOCATOR_GROUPS_FILE,
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
                "selected_accessions_count": selected_accessions_count,
                "selected_exhibit_like_accessions_count": selected_exhibit_like_count,
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
                "limit": effective_filters.limit,
                "accession_limit": effective_filters.accession_limit,
                "min_exhibit_like": effective_filters.min_exhibit_like,
                "xbrl_only": bool(effective_filters.xbrl_only),
                "counts": counts,
                "selected_rows": total_rows,
                "active_targets_count": total_rows,
                "unique_locators_count": locator_count,
                "selected_accessions_count": selected_accessions_count,
                "selected_exhibit_like_accessions_count": selected_exhibit_like_count,
                "request_fingerprint": hashlib.sha256(
                    json.dumps(request, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            }
            if cohort_input is not None:
                cohort_record, _ = cohort_input
                plan_meta["cohort_id"] = cohort_record.cohort_id
                plan_meta["cohort_dataset_sha256"] = cohort_record.dataset_sha256
            plan_meta = write_plan_documents(staging, plan_meta, selection_report)

    return plan_meta


__all__ = ["plan"]
