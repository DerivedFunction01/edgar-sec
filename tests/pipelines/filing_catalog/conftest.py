"""Shared fixtures for the filing-catalog pipeline tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.pipelines.filing_catalog.paths import (
    SNAPSHOT_FILE_NAME,
    TARGETS_DIR_NAME,
    FilingCatalogPaths,
    resolve_filing_catalog_paths,
    target_part_name,
)

EXPECTED_TARGETS = "expected_filing_targets.csv"
EXPECTED_PROFILES = "expected_company_profiles.csv"


@pytest.fixture
def catalog_paths(tmp_path: Path) -> FilingCatalogPaths:
    """A catalog layout rooted in a throwaway directory."""
    return resolve_filing_catalog_paths(tmp_path / "artifacts")


@pytest.fixture
def catalog_snapshot(
    tmp_path: Path, sample_source: Path
) -> tuple[dict[str, Any], Path]:
    """Materialize the committed fixture into a throwaway artifacts root."""
    from edgar_sec.pipelines.filing_catalog.catalog_job import materialize

    artifacts_root = tmp_path / "art"
    manifest = materialize(sample_source, artifacts_root)
    snapshot_dir = resolve_filing_catalog_paths(artifacts_root).snapshot_dir(
        str(manifest["catalog_id"])
    )
    return manifest, snapshot_dir


@pytest.fixture
def published_targets(catalog_snapshot: tuple[dict[str, Any], Path]) -> pa.Table:
    """The published filing-target shard."""
    _, snapshot_dir = catalog_snapshot
    targets = snapshot_dir / TARGETS_DIR_NAME / target_part_name(0)
    return pq.read_table(targets)


@pytest.fixture
def published_profiles(catalog_snapshot: tuple[dict[str, Any], Path]) -> pa.Table:
    """The published company-profile dataset."""
    _, snapshot_dir = catalog_snapshot
    return pq.read_table(snapshot_dir / SNAPSHOT_FILE_NAME)
