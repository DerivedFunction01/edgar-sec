"""The locator-group schema a policy plan publishes, per scope."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_BASE_COLUMNS,
    LOCATOR_POLICY_COLUMNS,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_FILE,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planning.deterministic import plan
from edgar_sec.pipelines.filing_catalog.planning.policy import plan_policy
from tests.pipelines.filing_catalog.planning.policy_support import (
    _artifacts_root,
    _policy,
)


def test_policy_plan_locator_groups_are_the_nineteen_column_schema(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Plan locator groups include the selection dimensions for audit."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    schema = pq.read_schema(plan_dir / LOCATOR_GROUPS_FILE)
    assert list(schema.names) == list(LOCATOR_POLICY_COLUMNS)
    assert len(schema.names) == 19
    assert set(LOCATOR_BASE_COLUMNS) <= set(schema.names)


def test_stage_a_locator_schema_stays_narrow(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A consumer must not be able to assume 18 columns in a deterministic plan."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan(str(manifest["catalog_id"]), artifacts_root, forms=("10-K",))
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    schema = pq.read_schema(plan_dir / LOCATOR_GROUPS_FILE)
    assert list(schema.names) == list(LOCATOR_BASE_COLUMNS)
    assert len(schema.names) == 8


def test_policy_plan_partitions_targets_by_form(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    assert set(meta["counts"]) == {"10-K", "8-K"}
    for form, count in meta["counts"].items():
        partition = plan_dir / "targets" / f"form={form}" / "data.parquet"
        assert partition.is_file()
        assert pq.read_metadata(partition).num_rows == count
    assert meta["selected_rows"] == sum(meta["counts"].values())
