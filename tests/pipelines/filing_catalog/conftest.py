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
)

EXPECTED_TARGETS = "expected_filing_targets.csv"
EXPECTED_PROFILES = "expected_company_profiles.csv"


@pytest.fixture
def catalog_paths(tmp_path: Path) -> FilingCatalogPaths:
    """A catalog layout rooted in a throwaway directory."""
    return resolve_filing_catalog_paths(tmp_path / "artifacts")


@pytest.fixture
def catalog_artifacts_root(tmp_path: Path) -> Path:
    """The artifacts root the catalog fixture publishes into.

    Exposed as its own fixture so tests resolve a catalog path with the same
    resolver production uses. Deriving it by walking ``parents[N]`` off a
    snapshot directory silently breaks whenever the layout gains or loses a
    level, which is how a layout change turns into a wall of unrelated failures.
    """
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
    """Every published target shard, in source-part order.

    The catalog writes one shard per Phase 1 source part, so a fixture that read
    only ``part-00000.parquet`` would silently cover a fraction of the dataset and
    every assertion built on it — uniqueness, ordering, totals — would hold for
    that fraction alone.
    """
    _, snapshot_dir = catalog_snapshot
    files = sorted((snapshot_dir / TARGETS_DIR_NAME).glob("part-*.parquet"))
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
    return pq.read_table(snapshot_dir / SNAPSHOT_FILE_NAME)
