"""Unified end-to-end execution runner coordinating catalog, planning, and acquisition."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.runner.config import RunnerOptions, TargetSpec
from edgar_sec.infra.storage.duckdb import connect
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

    def __init__(self, options: RunnerOptions | None = None) -> None:
        self.options = options or RunnerOptions()
        self.catalog_paths = resolve_filing_catalog_paths(self.options.artifacts_root)
        self.planning_paths = resolve_document_planning_paths(
            self.options.artifacts_root
        )
        self.acquisition_paths = resolve_acquisition_paths(self.options.artifacts_root)

    def _resolve_catalog_plan(self, spec: TargetSpec) -> str:
        catalog_id = current_catalog_id(self.catalog_paths)
        if not catalog_id:
            raise RuntimeError("no active filing catalog discovered in artifacts")
        plan_meta = build_catalog_plan(
            catalog=catalog_id,
            output_root=self.catalog_paths.artifacts_root,
            forms=tuple(spec.forms) if spec.forms else None,
            document_suffixes=tuple(spec.suffixes) if spec.suffixes else None,
            dates=spec.dates,
            limit=spec.limit,
        )
        return str(plan_meta["plan_id"])

    def _resolve_profile_id(self, spec: TargetSpec) -> str:
        if spec.role == "primary":
            return "primary-only"
        if spec.role.upper().startswith("EX-"):
            from edgar_sec.pipelines.document_planning.profiles import (
                get_or_create_exhibit_profile,
            )

            profile = get_or_create_exhibit_profile(
                spec.role, profiles_root=self.planning_paths.profiles_root
            )
            return profile.profile_id
        return spec.role

    def run(self, spec: TargetSpec) -> FilingsResult:
        """Execute full pipeline end-to-end and return relational FilingsResult."""
        catalog_plan_id = self._resolve_catalog_plan(spec)
        profile_id = self._resolve_profile_id(spec)

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
            _LazySecTransport(lambda: self.options.sec_client)
            if self.options.sec_client is not None
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
                    requested_workers=self.options.workers,
                    retain_response_evidence=True,
                ),
                transport=transport,
                clock=lambda: datetime.now(UTC),
            )
        finally:
            transport.close()

        snapshot_id: str | None = None
        if self.options.publish_snapshot:
            from edgar_sec.pipelines.document_acquisition.snapshot.writer import (
                publish_acquisition_run,
            )

            publication = publish_acquisition_run(
                self.acquisition_paths,
                run_id,
                allow_errors=True,
            )
            snapshot_id = publication.snapshot_id

        target_parquet_glob = str(
            self.planning_paths.plan_dir(doc_plan_id)
            / PLAN_TARGETS_DIR
            / "**"
            / "*.parquet"
        )
        run_state_sqlite_path = self.acquisition_paths.run_state_path(run_id)

        return FilingsResult(
            run_id=run_id,
            plan_id=doc_plan_id,
            target_parquet_glob=target_parquet_glob,
            run_state_sqlite_path=run_state_sqlite_path,
            artifacts_root=self.acquisition_paths.artifacts_root,
            snapshot_id=snapshot_id,
        )


__all__ = ["PipelineRunner"]
