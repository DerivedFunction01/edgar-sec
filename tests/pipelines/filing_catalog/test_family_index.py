"""Fail-closed policy-plan family-index dependencies."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.engine.selection.policy import EraBand, SelectionPolicy
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.models import FamilyIndexRecord
from edgar_sec.pipelines.cohort.operations import FamilyIndexNotFoundError
from edgar_sec.infra.storage.cohort.paths import CohortPaths, resolve_cohort_paths
from edgar_sec.pipelines.filing_catalog.planner import plan_policy


def _policy() -> SelectionPolicy:
    return SelectionPolicy(
        corpus_id="policy_corpus",
        forms=["10-K"],
        era_bands=[EraBand(name="modern", start_year=2010)],
        base_content_units=1,
        reserve_size=0,
        seed_cik_path="__absent__",
    )


def _active_index(
    artifacts_root: Path,
) -> tuple[CohortPaths, CohortCatalog, str, FamilyIndexRecord]:
    paths = resolve_cohort_paths(artifacts_root)
    catalog = CohortCatalog(paths)
    universe_id = catalog.get_active_source_pointer("cik_lookup")
    assert universe_id is not None
    record = catalog.get_active_family_index(universe_id)
    assert record is not None
    return paths, catalog, universe_id, record


def test_planner_requires_publication_even_when_a_plan_is_cached(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    plan_policy(str(manifest["catalog_id"]), _policy(), catalog_artifacts_root)
    paths, _, universe_id, _ = _active_index(catalog_artifacts_root)
    with sqlite3.connect(paths.catalog_file) as connection:
        connection.execute(
            "DELETE FROM active_family_indices WHERE universe_cohort_id = ?",
            (universe_id,),
        )

    with pytest.raises(FamilyIndexNotFoundError, match="no family index is published"):
        plan_policy(str(manifest["catalog_id"]), _policy(), catalog_artifacts_root)


def test_index_id_participates_in_policy_plan_identity(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    original = plan_policy(
        str(manifest["catalog_id"]), _policy(), catalog_artifacts_root
    )
    paths, catalog, universe_id, record = _active_index(catalog_artifacts_root)
    replacement_id = hashlib.sha256(b"replacement family index").hexdigest()[:32]
    assert replacement_id != record.family_index_id
    replacement_path = paths.family_index_file(replacement_id)
    replacement_path.parent.mkdir(parents=True)
    shutil.copyfile(paths.resolve_relative_path(record.dataset_path), replacement_path)
    catalog.set_active_family_index(
        universe_id,
        replacement_id,
        record.rules_fingerprint,
        file_sha256(replacement_path),
    )

    replacement = plan_policy(
        str(manifest["catalog_id"]), _policy(), catalog_artifacts_root
    )

    assert replacement["family_index_id"] == replacement_id
    assert original["plan_id"] != replacement["plan_id"]


def test_planner_rejects_rules_stale_index(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    _, catalog, universe_id, record = _active_index(catalog_artifacts_root)
    catalog.set_active_family_index(
        universe_id,
        record.family_index_id,
        "f" * 64,
        record.dataset_sha256,
    )

    with pytest.raises(FamilyIndexNotFoundError, match="outdated assignment rules"):
        plan_policy(str(manifest["catalog_id"]), _policy(), catalog_artifacts_root)


def test_planner_rejects_corrupt_index_digest(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    paths, _, _, record = _active_index(catalog_artifacts_root)
    dataset = paths.resolve_relative_path(record.dataset_path)
    dataset.write_bytes(b"corrupted")

    with pytest.raises(FamilyIndexNotFoundError, match="digest mismatch"):
        plan_policy(str(manifest["catalog_id"]), _policy(), catalog_artifacts_root)


def test_planner_rejects_incompatible_index_schema(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    paths, catalog, universe_id, record = _active_index(catalog_artifacts_root)
    dataset = paths.resolve_relative_path(record.dataset_path)
    pq.write_table(pa.table({"unexpected": ["value"]}), dataset)
    catalog.set_active_family_index(
        universe_id,
        record.family_index_id,
        record.rules_fingerprint,
        file_sha256(dataset),
    )

    with pytest.raises(FamilyIndexNotFoundError, match="incompatible Parquet schema"):
        plan_policy(str(manifest["catalog_id"]), _policy(), catalog_artifacts_root)
