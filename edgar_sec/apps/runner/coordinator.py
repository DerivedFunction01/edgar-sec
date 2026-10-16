"""Unified end-to-end execution runner coordinating catalog, planning, and acquisition."""

from __future__ import annotations

import tempfile
import csv
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.client.resolver import resolve_entity_profile
from edgar_sec.apps.runner.config import FilingQuery, PipelineConfig
from edgar_sec.domain.identity import Cik
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import CohortPaths, resolve_cohort_paths
from edgar_sec.infra.storage.duckdb import connect, sql_identifier
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.pipelines.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.pipelines.document_acquisition.commands.common import (
    _LazySecTransport,
    response_byte_limit,
    sec_transport_factory,
)
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    project_acquisition_run,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths
from edgar_sec.pipelines.document_planning.planner import create_document_plan
from edgar_sec.pipelines.filing_catalog.discovery import current_catalog_id
from edgar_sec.pipelines.filing_catalog.paths import (
    PLAN_TARGETS_DIR,
    SNAPSHOT_FILE,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planning.deterministic import (
    plan as build_catalog_plan,
)


class PipelineRunner:
    """Coordinates verified pipeline primitives into high-throughput execution."""

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        root = self.config.artifacts_root
        self.catalog_paths = resolve_filing_catalog_paths(root)
        self.planning_paths = resolve_document_planning_paths(root)
        self.acquisition_paths = resolve_acquisition_paths(root)
        self.cohort_paths = resolve_cohort_paths(root)

    def _resolve_target_cohort(self, config: FilingQuery) -> str | None:
        input_path = Path(config.input_file) if config.input_file else None
        if input_path is not None and not input_path.is_file():
            input_path = None
        if not config.ciks and not config.tickers and input_path is None:
            return None

        catalog = CohortCatalog(self.cohort_paths)
        row_count = 0
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", encoding="utf-8", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                writer = csv.writer(tmp)
                writer.writerow(("cik_padded",))

                def add_cik(value: Any) -> None:
                    nonlocal row_count
                    writer.writerow((str(Cik.from_raw(value).value).zfill(10),))
                    row_count += 1

                for cik in config.ciks:
                    add_cik(cik)
                for ticker in config.tickers:
                    profile = resolve_entity_profile(ticker, self.config.artifacts_root)
                    if profile and profile.cik:
                        add_cik(profile.cik.value)

                if input_path is not None:
                    self._write_input_targets(input_path, writer, add_cik)
            if row_count == 0:
                return None
            res = ingest_file_to_cohort(
                tmp_path,
                catalog=catalog,
                paths=self.cohort_paths,
            )
            return res.cohort.cohort_id
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _write_input_targets(
        self,
        input_path: Path,
        writer: Any,
        add_cik: Any,
    ) -> None:
        is_parquet = input_path.suffix.lower() == ".parquet"
        reader = "read_parquet(?)" if is_parquet else "read_csv_auto(?)"
        with connect() as con:
            schema_cols = {
                str(row[0]).lower()
                for row in con.execute(
                    f"DESCRIBE SELECT * FROM {reader}", [str(input_path)]
                ).fetchall()
            }
            if "cik" in schema_cols or "source_cik" in schema_cols:
                col = sql_identifier("cik" if "cik" in schema_cols else "source_cik")
                cursor = con.execute(
                    f"SELECT DISTINCT {col} FROM {reader} WHERE {col} IS NOT NULL",
                    [str(input_path)],
                )
                while batch := cursor.fetchmany(resolve_read_batch_size()):
                    for (value,) in batch:
                        add_cik(value)
                return
            if "ticker" not in schema_cols:
                return
            tickers = (
                f"SELECT DISTINCT upper(trim(CAST(ticker AS VARCHAR))) AS ticker "
                f"FROM {reader} WHERE ticker IS NOT NULL AND trim(CAST(ticker AS VARCHAR)) <> ''"
            )
            profile_pattern = str(
                self.catalog_paths.snapshots_root / "**" / SNAPSHOT_FILE
            )
            try:
                cursor = con.execute(
                    "WITH source_tickers AS (" + tickers + "), mapped AS ("
                    "SELECT s.ticker, min(try_cast(p.cik AS BIGINT)) AS cik "
                    "FROM source_tickers s LEFT JOIN read_parquet(?) p "
                    "ON list_contains(list_transform(p.listings, x -> upper(x.ticker)), s.ticker) "
                    "GROUP BY s.ticker) SELECT ticker, cik FROM mapped ORDER BY ticker",
                    [str(input_path), profile_pattern],
                )
                while batch := cursor.fetchmany(resolve_read_batch_size()):
                    for ticker, cik in batch:
                        if cik is None:
                            profile = resolve_entity_profile(
                                str(ticker), self.config.artifacts_root
                            )
                            if profile and profile.cik:
                                add_cik(profile.cik.value)
                        else:
                            add_cik(cik)
            except Exception:
                cursor = con.execute(
                    "SELECT DISTINCT upper(trim(CAST(ticker AS VARCHAR))) "
                    f"FROM {reader} WHERE ticker IS NOT NULL ORDER BY 1",
                    [str(input_path)],
                )
                while batch := cursor.fetchmany(resolve_read_batch_size()):
                    for (ticker,) in batch:
                        profile = resolve_entity_profile(
                            str(ticker), self.config.artifacts_root
                        )
                        if profile and profile.cik:
                            add_cik(profile.cik.value)

    def _resolve_profile_id(self, roles: tuple[str, ...]) -> str:
        for role in roles:
            if role.upper().startswith("EX-"):
                from edgar_sec.pipelines.document_planning.profiles import (
                    get_or_create_exhibit_profile,
                )

                profile = get_or_create_exhibit_profile(
                    role, profiles_root=self.planning_paths.profiles_root
                )
                return profile.profile_id
        return "primary-only"

    def _resolve_catalog_plan(
        self, config: PipelineConfig, cohort_id: str | None
    ) -> str:
        catalog_id = current_catalog_id(self.catalog_paths)
        if not catalog_id:
            raise RuntimeError("no active filing catalog discovered in artifacts")
        plan_meta = build_catalog_plan(
            catalog=catalog_id,
            output_root=self.catalog_paths.artifacts_root,
            forms=tuple(config.forms) if config.forms else None,
            document_suffixes=tuple(config.suffixes) if config.suffixes else None,
            dates=config.resolved_date_string(),
            cohort=cohort_id,
            limit=config.limit,
        )
        return str(plan_meta["plan_id"])

    def run(self, config: FilingQuery | PipelineConfig | None = None) -> FilingsResult:
        """Execute full pipeline end-to-end and return relational FilingsResult."""
        cfg = config or self.config
        if not isinstance(cfg, PipelineConfig):
            cfg = PipelineConfig(
                tickers=cfg.tickers,
                ciks=cfg.ciks,
                accessions=cfg.accessions,
                input_file=cfg.input_file,
                forms=cfg.forms,
                dates=cfg.dates,
                roles=cfg.roles,
                suffixes=cfg.suffixes,
                limit=cfg.limit,
                operations=cfg.operations,
                artifacts_root=self.config.artifacts_root,
                workers=self.config.workers,
                sec_client=self.config.sec_client,
                cleanup=getattr(cfg, "cleanup", self.config.cleanup),
            )

        cohort_id = self._resolve_target_cohort(cfg)
        catalog_plan_id = self._resolve_catalog_plan(cfg, cohort_id)
        profile_id = self._resolve_profile_id(cfg.roles)

        doc_plan = create_document_plan(
            catalog_plan_id,
            profile_id,
            paths=self.planning_paths,
        )
        doc_plan_id = doc_plan.plan_id

        project_result = project_acquisition_run(
            doc_plan_id, paths=self.acquisition_paths
        )
        run_id = project_result.run_id

        transport = (
            _LazySecTransport(lambda: cfg.sec_client)
            if cfg.sec_client is not None
            else _LazySecTransport(sec_transport_factory)
        )
        try:
            max_response_bytes = response_byte_limit(None)
            execute_acquisition_run(
                run_id,
                retry_failures=False,
                paths=self.acquisition_paths,
                policy=AcquisitionPolicy(
                    max_response_bytes=max_response_bytes,
                    requested_workers=cfg.workers,
                    retain_response_evidence=True,
                ),
                transport=transport,
                clock=lambda: datetime.now(UTC),
            )
        finally:
            transport.close()

        snapshot_id: str | None = None

        target_parquet_glob = str(
            self.planning_paths.plan_dir(doc_plan_id)
            / PLAN_TARGETS_DIR
            / "**"
            / "*.parquet"
        )
        run_state_sqlite_path = self.acquisition_paths.run_state_path(run_id)

        effective_op = cfg.operations[0] if cfg.operations else "raw"
        result = FilingsResult(
            run_id=run_id,
            plan_id=doc_plan_id,
            target_parquet_glob=target_parquet_glob,
            run_state_sqlite_path=run_state_sqlite_path,
            artifacts_root=self.acquisition_paths.artifacts_root,
            snapshot_id=snapshot_id,
            operation=effective_op,
        )

        if cfg.cleanup in ("transient", "all"):
            from edgar_sec.apps.runner.cleanup import clear_plans, clear_transient
            from edgar_sec.apps.client.cache import DocumentCache

            cache = DocumentCache(artifacts_root=self.acquisition_paths.artifacts_root)
            preloaded_items = []
            for filing in result:
                data = filing.raw()
                filename = f"{run_id}/{Path(filing.primary_document_path).name}"
                if data is not None:
                    cache.put(
                        filing.accession.value,
                        filing.primary_cik.value,
                        filing.form,
                        filename,
                        data,
                    )
                accession = filing.accession.value
                preloaded_items.append(
                    replace(
                        filing,
                        primary_storage_path=None,
                        fetcher=lambda _f, a=accession, n=filename: cache.get(a, n),
                    )
                )
            clear_transient(self.acquisition_paths.artifacts_root, run_id=run_id)
            if cfg.cleanup == "all":
                clear_plans(self.planning_paths.artifacts_root, plan_id=doc_plan_id)
            result = FilingsResult(
                run_id=run_id,
                plan_id=doc_plan_id,
                target_parquet_glob=target_parquet_glob,
                run_state_sqlite_path=run_state_sqlite_path,
                artifacts_root=self.acquisition_paths.artifacts_root,
                snapshot_id=snapshot_id,
                operation=effective_op,
                items=tuple(preloaded_items),
            )

        return result


__all__ = ["PipelineRunner"]
