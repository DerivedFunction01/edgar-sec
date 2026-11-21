"""Publishing a policy plan bundle and the identity that names it."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import SCOPE_DETERMINISTIC
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.filing_catalog.catalog_job import materialize
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_FILE,
    REQUIRED_PLAN_FILES,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planning.deterministic import plan
from edgar_sec.pipelines.filing_catalog.planning.policy import plan_policy
from edgar_sec.pipelines.cohort.family_index import publish_family_index
from edgar_sec.pipelines.filing_catalog.publication import (
    PlanConflictError,
    plan_bundle_complete,
    plan_locator_keys,
)
from tests.pipelines.filing_catalog.planning.policy_support import (
    _artifacts_root,
    _policy,
)
from tests.support.cohorts import published_universe


def test_policy_plan_publishes_a_complete_bundle(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy()
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)

    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert plan_bundle_complete(plan_dir)
    assert meta["family_index_id"]
    for name in REQUIRED_PLAN_FILES:
        assert (plan_dir / name).is_file()


def test_policy_plan_id_is_content_derived_and_stable(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The same catalog and policy must resolve to the same bundle, not fork one."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy()
    first = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    second = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    assert first["plan_id"] == second["plan_id"]


def test_a_different_policy_publishes_a_different_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    baseline = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    other = plan_policy(
        str(manifest["catalog_id"]),
        _policy(base_content_units=2),
        artifacts_root,
    )
    assert baseline["plan_id"] != other["plan_id"]


def test_policy_and_deterministic_scopes_never_collide(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Both scopes publish locator_groups.parquet under a content-derived id."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    deterministic = plan(str(manifest["catalog_id"]), artifacts_root, forms=("10-K",))
    policy = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    assert deterministic["plan_id"] != policy["plan_id"]
    assert deterministic["scope"] == SCOPE_DETERMINISTIC


def test_an_incomplete_bundle_is_a_conflict_not_an_overwrite(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A published bundle is immutable, even when it is damaged."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy()
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    (plan_dir / LOCATOR_GROUPS_FILE).unlink()

    with pytest.raises(PlanConflictError, match="incomplete plan bundle"):
        plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)


def test_a_policy_rebuild_into_an_independent_root_is_identical(
    catalog_snapshot: tuple[dict[str, object], Path],
    tmp_path: Path,
    sample_source: Path,
) -> None:
    """A same-root call reuses the bundle, so it proves reuse, not reproducibility."""
    manifest, _ = catalog_snapshot
    policy = _policy()

    # Two independent roots, each with its own catalog snapshot.
    first_root = tmp_path / "a"
    second_root = tmp_path / "b"
    materialize(sample_source, first_root)
    materialize(sample_source, second_root)
    for root in (first_root, second_root):
        published_universe(root)
        paths = resolve_cohort_paths(root)
        publish_family_index(catalog=CohortCatalog(paths), paths=paths)

    first = plan_policy(str(manifest["catalog_id"]), policy, first_root)
    second = plan_policy(str(manifest["catalog_id"]), policy, second_root)

    assert first["plan_id"] == second["plan_id"]
    assert first["plan_fingerprint"] == second["plan_fingerprint"]
    assert first["counts"] == second["counts"]

    first_dir = resolve_filing_catalog_paths(first_root).plan_dir(first["plan_id"])
    second_dir = resolve_filing_catalog_paths(second_root).plan_dir(second["plan_id"])
    assert list(plan_locator_keys(first_dir)) == list(plan_locator_keys(second_dir))
    for partition in sorted(first_dir.glob("targets/form=*/data.parquet")):
        mirror = second_dir / partition.relative_to(first_dir)
        assert pq.read_table(partition).to_pylist() == pq.read_table(mirror).to_pylist()
