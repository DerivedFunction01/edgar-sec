"""The filing-catalog artifact layout, pinned because consumers resolve paths here
rather than concatenating strings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import edgar_sec.foundation.runtime.paths as foundation_paths
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.pipelines.filing_catalog.paths import (
    CURRENT_ALIAS,
    EXPANSION_METADATA_FILE,
    FORM_PARTITION_GLOB,
    FORM_PARTITION_KEY,
    PIPELINE_DIR,
    PLAN_TARGETS_DIR,
    PLANS_DIR,
    REQUIRED_PLAN_FILES,
    SEED_FILERS_FILE,
    form_partition_directory,
    form_partition_name,
    plan_target_file_path,
    plan_target_part_path,
    resolve_filing_catalog_paths,
    validate_safe_id,
    target_part_name,
)


@pytest.fixture()
def paths(tmp_path: Path):
    return resolve_filing_catalog_paths(tmp_path / "artifacts")


# --- roots -----------------------------------------------------------------


def test_catalog_root_is_under_the_pipeline_directory(paths) -> None:
    assert paths.catalog_root == paths.artifacts_root / PIPELINE_DIR


def test_snapshots_and_plans_are_sibling_directories(paths) -> None:
    """One published root per kind, both directly under the pipeline directory."""
    assert paths.snapshots_root == paths.catalog_root / foundation_paths.SNAPSHOTS_DIR
    assert paths.plans_root == paths.catalog_root / PLANS_DIR
    assert paths.snapshot_dir("cat-1").parent == paths.snapshots_root
    assert paths.plan_dir("plan-1").parent == paths.plans_root


def test_catalog_and_plan_ids_have_separate_namespaces(paths) -> None:
    """The separation cannot rest on both ids merely being content digests."""
    assert paths.snapshot_dir("same-id") != paths.plan_dir("same-id")


def test_catalog_file_lives_inside_the_snapshots_root(paths) -> None:
    """The SQLite DAG catalog sits in the snapshots root."""
    assert paths.catalog_file == paths.snapshots_root / "catalog.sqlite"


# --- identifiers -----------------------------------------------------------


def test_safe_identifier_rejects_a_path_traversal(tmp_path: Path) -> None:
    paths = resolve_filing_catalog_paths(tmp_path)
    with pytest.raises(ValueError, match="invalid identifier"):
        paths.plan_dir("../../etc")
    with pytest.raises(ValueError, match="invalid identifier"):
        validate_safe_id("a/b")


def test_an_unsafe_identifier_never_becomes_a_directory(paths) -> None:
    """A traversal must fail before it can escape the artifacts root."""
    with pytest.raises(ValueError):
        paths.snapshot_dir("../escape")


def test_form_partition_name_escapes_a_slash() -> None:
    assert form_partition_name("10-K/A") == "10-K_A"
    assert form_partition_name("10-K") == "10-K"


def test_plan_target_paths_share_the_catalog_layout_contract() -> None:
    assert FORM_PARTITION_KEY == "form"
    assert FORM_PARTITION_GLOB == "form=*"
    assert form_partition_directory("10-K/A") == "form=10-K_A"
    assert plan_target_file_path("10-K/A", "data.parquet") == (
        "targets/form=10-K_A/data.parquet"
    )
    assert plan_target_part_path("10-K/A", 2) == (
        "targets/form=10-K_A/part-00002.parquet"
    )


def test_form_partition_path_escapes_the_form() -> None:
    partition = (
        Path("/plans/p1") / PLAN_TARGETS_DIR / f"form={form_partition_name('8-K/A')}"
    )
    assert partition == Path("/plans/p1") / PLAN_TARGETS_DIR / "form=8-K_A"
    assert "/" not in partition.name


def test_target_parts_are_numbered_not_named_after_the_source() -> None:
    assert target_part_name(0) == "part-00000.parquet"
    assert target_part_name(12) == "part-00012.parquet"


# --- plan bundle members ---------------------------------------------------


def test_plan_targets_dir_is_inside_the_plan(paths) -> None:
    plan_dir = paths.plan_dir("p1")
    assert plan_dir / PLAN_TARGETS_DIR == (paths.plans_root / "p1" / PLAN_TARGETS_DIR)


def test_plan_seed_sidecar_is_inside_the_plan(paths) -> None:
    assert paths.plan_seed_filers("p1").parent == paths.plan_dir("p1")
    assert paths.plan_seed_filers("p1").name == SEED_FILERS_FILE


def test_expansion_metadata_is_inside_the_plan(paths) -> None:
    assert paths.plan_dir("p1") / EXPANSION_METADATA_FILE == (
        paths.plans_root / "p1" / EXPANSION_METADATA_FILE
    )


def test_transient_staging_is_outside_the_published_root(paths) -> None:
    """Staging must never land where a consumer looks for published state."""
    staging = paths.transient_catalog_dir("cat-1")
    assert "transient" in staging.parts
    assert paths.catalog_root not in staging.parents


def test_required_plan_files_are_named_constants() -> None:
    assert PLAN_FILE_NAME in REQUIRED_PLAN_FILES
    for name in REQUIRED_PLAN_FILES:
        assert "/" not in name, "a required file must be a name, not a path"
        assert ".." not in name


def test_current_alias_is_not_an_interpolated_path(paths) -> None:
    assert CURRENT_ALIAS == "current"
    assert paths.snapshot_dir(CURRENT_ALIAS) == paths.snapshots_root / CURRENT_ALIAS


# --- resolution ------------------------------------------------------------


def test_an_explicit_root_is_resolved_to_an_absolute_path(tmp_path: Path) -> None:
    paths = resolve_filing_catalog_paths(tmp_path / "sub" / ".." / "art")
    assert paths.artifacts_root == (tmp_path / "art").resolve()


def test_resolution_is_stable_for_one_root(tmp_path: Path) -> None:
    first = resolve_filing_catalog_paths(tmp_path)
    second = resolve_filing_catalog_paths(tmp_path)
    assert first.catalog_root == second.catalog_root
    assert first.plan_dir("p1") == second.plan_dir("p1")
