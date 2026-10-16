"""Unified end-to-end execution runner coordinating catalog, planning, and acquisition."""

from __future__ import annotations

import tempfile
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

    def _resolve_target_ciks(self, config: FilingQuery) -> tuple[str, ...]:
        ciks: list[str] = [str(Cik.from_raw(c).value).zfill(10) for c in config.ciks]
        for ticker in config.tickers:
            profile = resolve_entity_profile(ticker, self.config.artifacts_root)
            if profile and profile.cik:
                ciks.append(str(profile.cik.value).zfill(10))
        if config.input_file:
            path = Path(config.input_file)
            if path.is_file():
                is_parquet = path.suffix.lower() == ".parquet"
                with connect() as con:
                    describe_sql = (
                        "DESCRIBE SELECT * FROM read_parquet(?)"
                        if is_parquet
                        else "DESCRIBE SELECT * FROM read_csv_auto(?)"
                    )
                    schema_cols = {
                        r[0].lower()
                        for r in con.execute(describe_sql, [str(path)]).fetchall()
                    }
                    if "cik" in schema_cols or "source_cik" in schema_cols:
                        col = "cik" if "cik" in schema_cols else "source_cik"
                        safe_col = sql_identifier(col)
                        cik_sql = (
                            f"SELECT DISTINCT {safe_col} FROM read_parquet(?) WHERE {safe_col} IS NOT NULL"
                            if is_parquet
                            else f"SELECT DISTINCT {safe_col} FROM read_csv_auto(?) WHERE {safe_col} IS NOT NULL"
                        )
                        for r in con.execute(cik_sql, [str(path)]).fetchall():
                            ciks.append(str(Cik.from_raw(r[0]).value).zfill(10))
                    elif "ticker" in schema_cols:
                        ticker_sql = (
                            "SELECT DISTINCT ticker FROM read_parquet(?) WHERE ticker IS NOT NULL"
                            if is_parquet
                            else "SELECT DISTINCT ticker FROM read_csv_auto(?) WHERE ticker IS NOT NULL"
                        )
                        for r in con.execute(ticker_sql, [str(path)]).fetchall():
                            prof = resolve_entity_profile(
                                str(r[0]), self.config.artifacts_root
                            )
                            if prof and prof.cik:
                                ciks.append(str(prof.cik.value).zfill(10))
        return tuple(dict.fromkeys(ciks))

    def _create_ephemeral_cohort(self, ciks: tuple[str, ...]) -> str | None:
        if not ciks:
            return None
        catalog = CohortCatalog(self.cohort_paths)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write("cik_padded\n")
            for c in ciks:
                tmp.write(f"{c}\n")
            tmp_path = Path(tmp.name)
        try:
            res = ingest_file_to_cohort(
                tmp_path,
                catalog=catalog,
                paths=self.cohort_paths,
            )
            return res.record.cohort_id
        finally:
            tmp_path.unlink(missing_ok=True)

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
            )

        ciks = self._resolve_target_ciks(cfg)
        cohort_id = self._create_ephemeral_cohort(ciks)
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
        return FilingsResult(
            run_id=run_id,
            plan_id=doc_plan_id,
            target_parquet_glob=target_parquet_glob,
            run_state_sqlite_path=run_state_sqlite_path,
            artifacts_root=self.acquisition_paths.artifacts_root,
            snapshot_id=snapshot_id,
            operation=effective_op,
        )


__all__ = ["PipelineRunner"]
