"""Shared fixtures for the filing-catalog pipeline tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.pipelines.filing_catalog.paths import (
    SNAPSHOT_FILE,
    TARGETS_DIR,
    FilingCatalogPaths,
    resolve_filing_catalog_paths,
)
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.cohort.family_index import publish_family_index
from tests.support import published_universe

EXPECTED_TARGETS = "expected_filing_targets.csv"
EXPECTED_PROFILES = "expected_company_profiles.csv"


@pytest.fixture(autouse=True)
def universe_roster(catalog_artifacts_root: Path) -> Path:
    """Publish the universe and its immutable family index for policy plans."""
    dataset = published_universe(catalog_artifacts_root)
    paths = resolve_cohort_paths(catalog_artifacts_root)
    publish_family_index(catalog=CohortCatalog(paths), paths=paths)
    return dataset


@pytest.fixture
def catalog_paths(tmp_path: Path) -> FilingCatalogPaths:
    """A catalog layout rooted in a throwaway directory."""
    return resolve_filing_catalog_paths(tmp_path / "artifacts")


@pytest.fixture
def catalog_artifacts_root(tmp_path: Path) -> Path:
    """Its own fixture, so no test derives the root by walking ``parents[N]``."""
    return tmp_path / "art"


@pytest.fixture
def catalog_snapshot(
    catalog_artifacts_root: Path, sample_source: Path
) -> tuple[dict[str, Any], Path]:
    """Materialize the committed fixture into a throwaway artifacts root."""
    from edgar_sec.pipelines.filing_catalog.catalog_job import materialize

    manifest = materialize(sample_source, catalog_artifacts_root)
    snapshot_dir = resolve_filing_catalog_paths(catalog_artifacts_root).snapshot_dir(
        str(manifest["catalog_id"])
    )
    return manifest, snapshot_dir


@pytest.fixture
def published_target_files(catalog_snapshot: tuple[dict[str, Any], Path]) -> list[Path]:
    """One shard per source part; reading only the first would cover a fraction."""
    _, snapshot_dir = catalog_snapshot
    files = sorted((snapshot_dir / TARGETS_DIR).glob("part-*.parquet"))
    assert files, "catalog published no target shards"
    return files


@pytest.fixture
def published_targets(
    published_target_files: list[Path],
) -> pa.Table:
    """The published filing targets as one logical dataset across all shards."""
    return pa.concat_tables(
        [pq.read_table(path) for path in published_target_files],
        promote_options="default",
    )


@pytest.fixture
def published_profiles(catalog_snapshot: tuple[dict[str, Any], Path]) -> pa.Table:
    """The published company-profile dataset."""
    _, snapshot_dir = catalog_snapshot
    return pq.read_table(snapshot_dir / SNAPSHOT_FILE)
