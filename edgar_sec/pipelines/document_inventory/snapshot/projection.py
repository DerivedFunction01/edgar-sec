"""Bounded projection of published catalog plans into transient S4 work orders."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA_VERSION
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.index_pages.parser import PARSER_FINGERPRINT
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.foundation.runtime.resources import (
    RuntimeResourceProfile,
    derive_resources,
)
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
    sql_path_list,
)
from edgar_sec.pipelines.document_inventory.cohort import (
    CohortInputError,
)
from edgar_sec.pipelines.document_inventory.paths import (
    COHORT_ACCESSIONS_FILE,
    COHORT_SOURCES_FILE,
    FilingCatalogPaths,
    InventoryRunPaths,
    LOCATOR_GROUPS_FILE,
    PROJECTION_MANIFEST_FILE,
    WORK_ORDER_FILE,
    inventory_paths,
    inventory_run_paths,
    resolve_filing_catalog_paths,
)
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_inventory.run_manifest import (
    InventoryRunManifest,
    ManifestMismatchError,
    WORK_ORDER_VERSION,
    read_run_manifest,
    validate_run_manifest,
    validate_work_order,
    write_run_manifest,
    write_work_order,
)
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    LOOKUP_LAYOUT_VERSION,
    SNAPSHOT_RELATION_VERSION,
)
from edgar_sec.pipelines.document_inventory.snapshot.errors import BaseSnapshotError
from edgar_sec.pipelines.document_inventory.snapshot.projection_inputs import (
    base_snapshot_parts,
    catalog_plan_parts,
)

__all__ = ["PrefetchProjection", "project_catalog_plan"]

_ARCHIVE_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
_COHORT_ACCESSIONS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("filing_cik", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("index_url", pa.string()),
    ]
)
_COHORT_SOURCES_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("source_cik", pa.string()),
        ("first_seen_by", pa.string()),
    ]
)


@dataclass(frozen=True, slots=True)
class PrefetchProjection:
    run_id: str
    catalog_plan_id: str
    base_snapshot_id: str | None
    cohort_fingerprint: str
    work_order_digest: str
    work_order_rows: int
    explicit_refresh_salt: str | None
    paths: InventoryRunPaths


def _read_projection_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestMismatchError("projection manifest is unreadable") from exc
    if not isinstance(payload, dict):
        raise ManifestMismatchError("projection manifest must be an object")
    return payload


def _projection_sql(parts: list[tuple[str, Path, int, str]]) -> str:
    selects = [
        f"SELECT document_locator_key, source_cik, accession, form, filing_date, "
        f"report_date, {sql_literal(form)} AS _expected_form "
        f"FROM read_parquet({sql_literal(str(path))})"
        for form, path, _count, _digest in parts
    ]
    if not selects:
        return """CREATE TEMP TABLE raw_targets AS
            SELECT NULL::VARCHAR AS document_locator_key,
                   NULL::VARCHAR AS accession, NULL::VARCHAR AS source_cik,
                   NULL::VARCHAR AS form, NULL::VARCHAR AS filing_date,
                   NULL::VARCHAR AS report_date, NULL::VARCHAR AS _expected_form
            WHERE FALSE"""
    return "CREATE TEMP TABLE raw_targets AS " + " UNION ALL BY NAME ".join(selects)


def _hash_relations(accessions_path: Path, sources_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"document-inventory-cohort-v1\0")
    for label, path in (("accessions", accessions_path), ("sources", sources_path)):
        digest.update(label.encode("ascii") + b"\0")
        for batch_index, batch in enumerate(
            pq.ParquetFile(path).iter_batches(
                batch_size=resolve_parquet_read_batch_size()
            ),
            start=1,
        ):
            rows = batch.to_pylist()
            for row in rows:
                encoded = canonical_json(row).encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
            del rows
            if batch_index % 16 == 0:
                reclaim()
    return digest.hexdigest()


def _validate_output_schema(path: Path, schema: pa.Schema) -> None:
    actual = pq.ParquetFile(path).schema_arrow
    if actual.names != schema.names or any(
        actual.field(name).type != field.type
        for name, field in zip(schema.names, schema, strict=True)
    ):
        raise ManifestMismatchError(f"projection output schema mismatch: {path.name}")


def _work_items(connection: Any):
    reader = connection.execute(
        "SELECT accession, index_url FROM work_candidates ORDER BY accession"
    ).to_arrow_reader(batch_size=resolve_read_batch_size())
    for batch_index, batch in enumerate(reader, start=1):
        rows = batch.to_pylist()
        for row in rows:
            yield IndexWorkItem(AccessionNumber(row["accession"]), row["index_url"])
        del rows
        if batch_index % 16 == 0:
            reclaim()


def _intent_id(
    *,
    catalog_id: str,
    catalog_plan_id: str,
    base_snapshot_id: str | None,
    base_manifest_sha256: str | None,
    cohort_fingerprint: str,
    chunk_size: int,
    refresh_salt: str | None,
) -> str:
    return (
        "run-"
        + canonical_hash(
            {
                "intent_version": "inventory-run-intent-v1",
                "catalog_id": catalog_id,
                "catalog_plan_id": catalog_plan_id,
                "base_snapshot_id": base_snapshot_id,
                "base_manifest_sha256": base_manifest_sha256,
                "cohort_fingerprint": cohort_fingerprint,
                "parser_version": PARSER_FINGERPRINT,
                "snapshot_relation_version": SNAPSHOT_RELATION_VERSION,
                "entry_schema_version": ENTRY_SCHEMA_VERSION,
                "lookup_layout_version": LOOKUP_LAYOUT_VERSION,
                "work_order_version": WORK_ORDER_VERSION,
                "chunk_size": chunk_size,
                "refresh_salt": refresh_salt,
            }
        )[:28]
    )


def _run_manifest(
    paths: InventoryRunPaths,
    *,
    base_snapshot_id: str | None,
    plan_id: str,
    cohort_fingerprint: str,
    chunk_size: int,
    explicit_refresh: bool,
    work_order_path: Path,
) -> InventoryRunManifest:
    kwargs = {
        "parent_snapshot_id": base_snapshot_id or "",
        "canonical_cohort_id": cohort_fingerprint,
        "source_identity": f"filing-catalog-plan:{plan_id}",
        "parser_version": PARSER_FINGERPRINT,
        "chunk_size": chunk_size,
        "refresh_mode": "force" if explicit_refresh else "normal",
        "fetch_mode": "force_refresh" if explicit_refresh else "live",
        "work_order_path": work_order_path,
        "fixture_id": None,
    }
    existing = read_run_manifest(paths)
    if existing is None:
        return write_run_manifest(paths, **kwargs)
    return validate_run_manifest(
        existing,
        run_id=paths.run_id,
        **kwargs,
    )


def _validate_existing_projection(
    paths: InventoryRunPaths,
    expected: dict[str, Any],
    *,
    plan_id: str,
    base_snapshot_id: str | None,
    chunk_size: int,
    explicit_refresh: bool,
) -> PrefetchProjection:
    manifest_path = paths.projection_manifest_path()
    manifest = _read_projection_manifest(manifest_path)
    comparable = {
        key: value for key, value in expected.items() if key not in {"outputs"}
    }
    actual = {key: value for key, value in manifest.items() if key not in {"outputs"}}
    if actual != comparable:
        raise ManifestMismatchError(f"projection identity mismatch for {paths.run_id}")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ManifestMismatchError("projection output metadata is missing")
    output_paths = {
        "cohort_accessions": paths.cohort_accessions_path(),
        "cohort_sources": paths.cohort_sources_path(),
        "work_order": paths.work_order_path(),
    }
    for name, path in output_paths.items():
        record = outputs.get(name)
        if not isinstance(record, dict) or not path.is_file():
            raise ManifestMismatchError(f"projection output missing: {name}")
        if record.get("path") != path.name:
            raise ManifestMismatchError(f"projection output path mismatch: {name}")
        if file_sha256(path) != record.get("sha256"):
            raise ManifestMismatchError(f"projection output digest mismatch: {name}")
    _validate_output_schema(paths.cohort_accessions_path(), _COHORT_ACCESSIONS_SCHEMA)
    _validate_output_schema(paths.cohort_sources_path(), _COHORT_SOURCES_SCHEMA)
    cohort_fingerprint = _hash_relations(
        paths.cohort_accessions_path(), paths.cohort_sources_path()
    )
    if cohort_fingerprint != manifest.get("cohort_fingerprint"):
        raise ManifestMismatchError("projection cohort fingerprint mismatch")
    work_identity = validate_work_order(paths.work_order_path())
    if work_identity.digest != manifest.get(
        "work_order_digest"
    ) or work_identity.row_count != manifest.get("work_order_rows"):
        raise ManifestMismatchError("projection work-order identity mismatch")
    _run_manifest(
        paths,
        base_snapshot_id=base_snapshot_id,
        plan_id=plan_id,
        cohort_fingerprint=cohort_fingerprint,
        chunk_size=chunk_size,
        explicit_refresh=explicit_refresh,
        work_order_path=paths.work_order_path(),
    )
    return PrefetchProjection(
        paths.run_id,
        plan_id,
        base_snapshot_id,
        cohort_fingerprint,
        work_identity.digest,
        work_identity.row_count,
        manifest.get("explicit_refresh_salt"),
        paths,
    )


def project_catalog_plan(
    catalog_plan_id: str,
    *,
    artifacts_root: Path | str,
    catalog_paths: FilingCatalogPaths | None = None,
    profile: RuntimeResourceProfile | None = None,
    archive_base_url: str = _ARCHIVE_BASE_URL,
    chunk_size: int | None = None,
    explicit_refresh: bool = False,
    explicit_refresh_salt: str | None = None,
    base_snapshot_id: str | None = None,
    branch_name: str = "main",
) -> PrefetchProjection:
    """Persist the full cohort projection and pre-fetch missing-accession work order.
    ``base_snapshot_id`` selects the lineage base; an explicit base must match the
    branch tip, so historical bases require a branch created at that tip first.
    """
    if not archive_base_url.startswith(("https://", "http://")):
        raise ValueError("archive_base_url must be an HTTP(S) URL")
    if explicit_refresh_salt is not None and (
        not explicit_refresh or not explicit_refresh_salt
    ):
        raise ValueError("explicit_refresh_salt requires explicit_refresh and a value")
    refresh_salt = explicit_refresh_salt or (
        uuid.uuid4().hex if explicit_refresh else None
    )
    settings = resolve_settings(include=["runtime"])
    effective_chunk_size = int(
        settings["runtime.chunk_size"] if chunk_size is None else chunk_size
    )
    if effective_chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    resources = profile or derive_resources()
    resolved_catalog_paths = catalog_paths or resolve_filing_catalog_paths(
        artifacts_root
    )
    plan_root, plan, parts, plan_file_sha, locator_file_sha = catalog_plan_parts(
        catalog_plan_id, resolved_catalog_paths
    )
    locator_path = plan_root / LOCATOR_GROUPS_FILE
    base_paths = inventory_paths(artifacts_root)

    if base_snapshot_id is not None:
        catalog = DAGCatalog(base_paths.snapshots_root)
        current = catalog.read_pointer(branch_name)
        observed_tip = str(current["snapshot_id"]) if current else None
        if observed_tip != base_snapshot_id:
            raise BaseSnapshotError(
                f"base snapshot {base_snapshot_id!r} does not match the tip of "
                f"branch {branch_name!r} ({observed_tip!r}); create a branch at the "
                "requested base with 'inventory dag branch create --from <id>' "
                "before publishing there"
            )
    snapshot_id, base_parts, base_manifest_sha = base_snapshot_parts(
        base_paths, snapshot_id=base_snapshot_id, branch_name=branch_name
    )
    pinned_base_snapshot_id = snapshot_id
    source_id = f"plan:{catalog_plan_id}"

    staging_parent = base_paths.projection_staging_root
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix="projection-", dir=staging_parent))
    connection = None
    stage_complete = False
    try:
        connection = connect(resources)
        connection.execute(_projection_sql(parts))
        target_rows = connection.execute("SELECT count(*) FROM raw_targets").fetchone()[
            0
        ]
        if target_rows != plan["selected_rows"]:
            raise CohortInputError(
                "invalid_bundle", detail="read target row count differs from the plan"
            )
        bad_rows = connection.execute(
            """
            SELECT count(*) FROM raw_targets
            WHERE document_locator_key IS NULL OR trim(document_locator_key) = ''
               OR accession IS NULL OR source_cik IS NULL OR form IS NULL
               OR filing_date IS NULL
               OR (report_date IS NOT NULL AND trim(report_date) <> ''
                   AND try_cast(trim(report_date) AS DATE) IS NULL)
               OR trim(form) = '' OR trim(form) <> _expected_form
               OR NOT regexp_matches(trim(accession), '^[0-9]{10}-[0-9]{2}-[0-9]{6}$|^[0-9]{18}$')
               OR NOT regexp_matches(trim(source_cik), '^[0-9]+$')
               OR length(trim(source_cik)) > 10
               OR try_cast(trim(source_cik) AS BIGINT) > 9999999999
               OR try_cast(trim(filing_date) AS DATE) IS NULL
            """
        ).fetchone()[0]
        if bad_rows:
            raise CohortInputError(
                "invalid_bundle", detail=f"target plan has {bad_rows} invalid rows"
            )
        connection.execute(
            f"CREATE TEMP TABLE plan_locator_keys AS SELECT document_locator_key "
            f"FROM read_parquet({sql_literal(str(locator_path))})"
        )
        duplicate_locator = connection.execute(
            """
            SELECT document_locator_key FROM plan_locator_keys
            GROUP BY document_locator_key HAVING count(*) > 1 LIMIT 1
            """
        ).fetchone()
        if duplicate_locator:
            raise CohortInputError(
                "invalid_bundle", detail="plan locator keys are not unique"
            )
        locator_difference = connection.execute(
            """
            SELECT 1
            FROM (SELECT DISTINCT document_locator_key FROM raw_targets) target
            WHERE NOT EXISTS (
                SELECT 1 FROM plan_locator_keys locator
                WHERE locator.document_locator_key = target.document_locator_key
            )
            UNION ALL
            SELECT 1 FROM plan_locator_keys locator
            WHERE NOT EXISTS (
                SELECT 1 FROM raw_targets target
                WHERE target.document_locator_key = locator.document_locator_key
            )
            LIMIT 1
            """
        ).fetchone()
        if locator_difference:
            raise CohortInputError(
                "invalid_bundle",
                detail="target rows differ from published locator groups",
            )
        connection.execute(
            """
            CREATE TEMP TABLE normalized_observations AS
            SELECT
                CASE
                    WHEN regexp_matches(trim(accession), '^[0-9]{18}$') THEN
                        substr(trim(accession), 1, 10) || '-' ||
                        substr(trim(accession), 11, 2) || '-' || substr(trim(accession), 13, 6)
                    ELSE trim(accession)
                END AS accession,
                lpad(cast(try_cast(trim(source_cik) AS BIGINT) AS VARCHAR), 10, '0') AS source_cik,
                trim(form) AS form,
                cast(try_cast(trim(filing_date) AS DATE) AS VARCHAR) AS filing_date,
                CASE
                    WHEN report_date IS NULL OR trim(report_date) = '' THEN NULL
                    ELSE cast(try_cast(trim(report_date) AS DATE) AS VARCHAR)
                END AS report_date
            FROM raw_targets
            """
        )
        duplicate_conflict = connection.execute(
            """
            SELECT accession, source_cik,
                   count(DISTINCT form) AS forms,
                   count(DISTINCT filing_date) AS filing_dates,
                   count(DISTINCT coalesce(report_date, '<null>')) AS report_dates
            FROM normalized_observations
            GROUP BY accession, source_cik
            HAVING forms > 1 OR filing_dates > 1 OR report_dates > 1
            LIMIT 1
            """
        ).fetchone()
        if duplicate_conflict:
            accession = AccessionNumber.from_any(duplicate_conflict[0])
            if duplicate_conflict[2] > 1:
                code = "conflicting_form"
                detail = "conflicting form values for duplicate source observation"
            elif duplicate_conflict[3] > 1:
                code = "conflicting_filing_date"
                detail = "conflicting filing dates for duplicate source observation"
            else:
                code = "conflicting_report_date"
                detail = "conflicting report dates for duplicate source observation"
            raise CohortInputError(
                code,
                accession,
                detail=f"{detail} (CIK {duplicate_conflict[1]})",
            )
        accession_conflict = connection.execute(
            """
            SELECT accession,
                   count(DISTINCT form) AS forms,
                   count(DISTINCT filing_date) AS filing_dates,
                   count(DISTINCT report_date) AS report_dates
            FROM normalized_observations
            GROUP BY accession
            HAVING forms > 1 OR filing_dates > 1 OR report_dates > 1
            LIMIT 1
            """
        ).fetchone()
        if accession_conflict:
            accession = AccessionNumber.from_any(accession_conflict[0])
            if accession_conflict[1] > 1:
                code = "conflicting_form"
            elif accession_conflict[2] > 1:
                code = "conflicting_filing_date"
            else:
                code = "conflicting_report_date"
            raise CohortInputError(code, accession)

        connection.execute(
            """
            CREATE TEMP TABLE cohort_accessions AS
            SELECT accession,
                   substr(replace(accession, '-', ''), 1, 10) AS filing_cik,
                   min(form) AS form,
                   min(filing_date) AS filing_date,
                   max(report_date) AS report_date
            FROM normalized_observations
            GROUP BY accession
            """
        )
        connection.execute(
            """
            CREATE TEMP TABLE cohort_sources AS
            SELECT DISTINCT accession, source_cik
            FROM normalized_observations
            """
        )
        connection.execute(
            """
            CREATE TEMP TABLE cohort_archive_ciks AS
            SELECT accession, min(source_cik) AS archive_cik
            FROM cohort_sources
            GROUP BY accession
            """
        )
        base_files = [str(path) for path, _count, _digest in base_parts]
        if base_files:
            connection.execute(
                f"CREATE TEMP TABLE base_accessions AS SELECT accession, filing_cik, form, filing_date, report_date "
                f"FROM read_parquet({sql_path_list(base_files)})"
            )
        else:
            connection.execute(
                """
                CREATE TEMP TABLE base_accessions (
                    accession VARCHAR, filing_cik VARCHAR, form VARCHAR,
                    filing_date VARCHAR, report_date VARCHAR
                )
                """
            )
        base_row_count = connection.execute(
            "SELECT count(*) FROM base_accessions"
        ).fetchone()[0]
        if base_row_count != sum(count for _path, count, _digest in base_parts):
            raise BaseSnapshotError(
                "base snapshot accession row count changed while reading"
            )
        invalid_base = connection.execute(
            """
            SELECT accession
            FROM base_accessions
            WHERE accession IS NULL
               OR NOT regexp_matches(accession, '^[0-9]{10}-[0-9]{2}-[0-9]{6}$')
               OR filing_cik IS NULL
               OR NOT regexp_matches(filing_cik, '^[0-9]{10}$')
               OR filing_cik <> substr(replace(accession, '-', ''), 1, 10)
               OR form IS NULL OR trim(form) = '' OR trim(form) <> form
               OR try_cast(filing_date AS DATE) IS NULL
               OR strftime(try_cast(filing_date AS DATE), '%Y-%m-%d') <> filing_date
               OR (report_date IS NOT NULL AND (
                   try_cast(report_date AS DATE) IS NULL
                   OR strftime(try_cast(report_date AS DATE), '%Y-%m-%d') <> report_date
               ))
            LIMIT 1
            """
        ).fetchone()
        if invalid_base:
            raise BaseSnapshotError("base snapshot contains invalid accession facts")
        duplicate_base = connection.execute(
            "SELECT accession FROM base_accessions GROUP BY accession HAVING count(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate_base:
            raise BaseSnapshotError(
                f"base snapshot has duplicate accession {duplicate_base[0]}"
            )
        metadata_mismatch = connection.execute(
            """
            SELECT c.accession
            FROM cohort_accessions c
            JOIN base_accessions b USING (accession)
            WHERE c.form <> b.form OR c.filing_date <> b.filing_date
               OR (c.report_date IS NOT NULL AND b.report_date IS NOT NULL
                   AND c.report_date <> b.report_date)
            LIMIT 1
            """
        ).fetchone()
        if metadata_mismatch:
            raise CohortInputError(
                "invalid_bundle",
                AccessionNumber.from_any(metadata_mismatch[0]),
                detail="filing metadata conflicts with the base snapshot",
            )

        base_url = archive_base_url.rstrip("/")
        connection.execute(
            f"""
            CREATE TEMP TABLE cohort_accessions_with_url AS
            SELECT facts.accession, facts.filing_cik, facts.form,
                   facts.filing_date, facts.report_date,
                   {sql_literal(base_url)} || '/' ||
                   cast(try_cast(route.archive_cik AS BIGINT) AS VARCHAR) || '/' ||
                   replace(facts.accession, '-', '') || '/' || facts.accession || '-index.html' AS index_url
            FROM cohort_accessions facts
            JOIN cohort_archive_ciks route USING (accession)
            """
        )
        connection.execute(
            """
            CREATE TEMP TABLE work_candidates AS
            SELECT c.accession, c.index_url
            FROM cohort_accessions_with_url c
            LEFT JOIN base_accessions b USING (accession)
            WHERE ? OR b.accession IS NULL
            """,
            [explicit_refresh],
        )

        accessions_stage = staging_root / COHORT_ACCESSIONS_FILE
        sources_stage = staging_root / COHORT_SOURCES_FILE
        work_order_stage = staging_root / WORK_ORDER_FILE
        accession_count = copy_query_to_parquet(
            connection,
            "SELECT accession, filing_cik, form, filing_date, report_date, index_url "
            "FROM cohort_accessions_with_url ORDER BY accession",
            accessions_stage,
        )
        source_count = copy_query_to_parquet(
            connection,
            f"SELECT accession, source_cik, {sql_literal(source_id)} AS first_seen_by "
            "FROM cohort_sources ORDER BY source_cik, accession",
            sources_stage,
        )
        work_identity = write_work_order(work_order_stage, _work_items(connection))
        _validate_output_schema(accessions_stage, _COHORT_ACCESSIONS_SCHEMA)
        _validate_output_schema(sources_stage, _COHORT_SOURCES_SCHEMA)
        if (
            file_sha256(plan_root / PLAN_FILE_NAME) != plan_file_sha
            or file_sha256(locator_path) != locator_file_sha
            or any(file_sha256(path) != digest for _form, path, _count, digest in parts)
            or any(file_sha256(path) != digest for path, _count, digest in base_parts)
            or (
                pinned_base_snapshot_id is not None
                and DAGCatalog(base_paths.snapshots_root).get_manifest_sha256(
                    pinned_base_snapshot_id
                )
                != base_manifest_sha
            )
        ):
            raise CohortInputError(
                "invalid_bundle",
                detail="published catalog plan changed during projection",
            )
        cohort_fingerprint = _hash_relations(accessions_stage, sources_stage)
        run_id = _intent_id(
            catalog_id=str(plan["catalog_id"]),
            catalog_plan_id=catalog_plan_id,
            base_snapshot_id=pinned_base_snapshot_id,
            base_manifest_sha256=base_manifest_sha,
            cohort_fingerprint=cohort_fingerprint,
            chunk_size=effective_chunk_size,
            refresh_salt=refresh_salt,
        )
        input_parts = [
            {
                "form": form,
                "path": path.relative_to(plan_root).as_posix(),
                "row_count": count,
                "sha256": digest,
            }
            for form, path, count, digest in parts
        ]
        projection_manifest = {
            "projection_version": "1",
            "run_id": run_id,
            "catalog_plan_id": catalog_plan_id,
            "catalog_id": str(plan["catalog_id"]),
            "scope": plan["scope"],
            "plan_schema_version": plan["plan_schema_version"],
            "plan_sha256": plan_file_sha,
            "locator_groups_sha256": locator_file_sha,
            "target_parts": input_parts,
            "base_snapshot_id": pinned_base_snapshot_id,
            "base_manifest_sha256": base_manifest_sha,
            "base_accession_parts": [
                {
                    "path": str(path.relative_to(base_paths.snapshots_root)),
                    "row_count": row_count,
                    "sha256": digest,
                }
                for path, row_count, digest in base_parts
            ],
            "parser_version": PARSER_FINGERPRINT,
            "snapshot_relation_version": SNAPSHOT_RELATION_VERSION,
            "entry_schema_version": ENTRY_SCHEMA_VERSION,
            "lookup_layout_version": LOOKUP_LAYOUT_VERSION,
            "cohort_fingerprint": cohort_fingerprint,
            "cohort_accession_rows": accession_count,
            "cohort_source_rows": source_count,
            "work_order_digest": work_identity.digest,
            "work_order_rows": work_identity.row_count,
            "work_order_version": WORK_ORDER_VERSION,
            "chunk_size": effective_chunk_size,
            "explicit_refresh": explicit_refresh,
            "explicit_refresh_salt": refresh_salt,
            "archive_base_url": base_url,
            "outputs": {
                "cohort_accessions": {
                    "path": COHORT_ACCESSIONS_FILE,
                    "sha256": file_sha256(accessions_stage),
                },
                "cohort_sources": {
                    "path": COHORT_SOURCES_FILE,
                    "sha256": file_sha256(sources_stage),
                },
                "work_order": {
                    "path": WORK_ORDER_FILE,
                    "sha256": file_sha256(work_order_stage),
                },
            },
        }
        atomic_write_json(staging_root / PROJECTION_MANIFEST_FILE, projection_manifest)
        stage_complete = True
    finally:
        if connection is not None:
            connection.close()
        if not stage_complete:
            shutil.rmtree(staging_root, ignore_errors=True)

    run_paths = inventory_run_paths(artifacts_root, run_id)
    try:
        if run_paths.run_root.exists():
            projection = _validate_existing_projection(
                run_paths,
                projection_manifest,
                plan_id=catalog_plan_id,
                base_snapshot_id=pinned_base_snapshot_id,
                chunk_size=effective_chunk_size,
                explicit_refresh=explicit_refresh,
            )
            return projection
        run_paths.run_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_root, run_paths.run_root)
        _run_manifest(
            run_paths,
            base_snapshot_id=pinned_base_snapshot_id,
            plan_id=catalog_plan_id,
            cohort_fingerprint=cohort_fingerprint,
            chunk_size=effective_chunk_size,
            explicit_refresh=explicit_refresh,
            work_order_path=run_paths.work_order_path(),
        )
        return PrefetchProjection(
            run_id,
            catalog_plan_id,
            pinned_base_snapshot_id,
            cohort_fingerprint,
            work_identity.digest,
            work_identity.row_count,
            refresh_salt,
            run_paths,
        )
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
