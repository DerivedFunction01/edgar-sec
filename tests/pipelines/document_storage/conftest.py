"""Shared fixtures for the document-storage tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.cohort.family_index import publish_family_index
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths
from tests.support import era_submission_metadata, published_universe


@pytest.fixture
def catalog_artifacts_root(tmp_path: Path) -> Path:
    return tmp_path / "art"


@pytest.fixture
def universe_roster(catalog_artifacts_root: Path) -> Path:
    dataset = published_universe(catalog_artifacts_root)
    paths = resolve_cohort_paths(catalog_artifacts_root)
    publish_family_index(catalog=CohortCatalog(paths), paths=paths)
    return dataset


def _publish_plan(source: Path, root: Path) -> tuple[dict[str, Any], Path]:
    from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
    from edgar_sec.pipelines.filing_catalog.planner import plan

    manifest = materialize(source, root)
    meta = plan(str(manifest["catalog_id"]), root)
    return meta, resolve_filing_catalog_paths(root).plan_dir(meta["plan_id"])


@pytest.fixture
def era_plan(
    catalog_artifacts_root: Path, universe_roster: Path, tmp_path: Path
) -> tuple[dict[str, Any], Path]:
    """A deterministic plan holding pre-2005 filings, so the gate has a real population."""
    return _publish_plan(
        era_submission_metadata(tmp_path / "era_submission_metadata.parquet"),
        catalog_artifacts_root,
    )


@pytest.fixture
def era_plan_dir(era_plan: tuple[dict[str, Any], Path]) -> Path:
    _meta, plan_dir = era_plan
    return plan_dir


@pytest.fixture
def era_catalog_plan(era_plan_dir: Path) -> Any:
    from edgar_sec.pipelines.document_storage.catalog_plan import CatalogPlan

    return CatalogPlan(era_plan_dir, chunk_size=64)
