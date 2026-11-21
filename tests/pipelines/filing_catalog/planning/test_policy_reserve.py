"""The reserve pool a policy plan writes beside its active locators."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_FILE,
    RESERVE_TARGETS_FILE,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planning.policy import plan_policy
from tests.pipelines.filing_catalog.planning.policy_support import (
    _artifacts_root,
    _policy,
)


def test_policy_plan_writes_a_reserve_pool(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    reserve = plan_dir / RESERVE_TARGETS_FILE
    assert reserve.is_file()
    assert pq.read_metadata(reserve).num_rows == meta["reserve_count"]


def test_reserve_is_disjoint_from_the_active_locators(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    active = set(
        pq.read_table(plan_dir / LOCATOR_GROUPS_FILE)[
            "document_locator_key"
        ].to_pylist()
    )
    reserve = set(
        pq.read_table(plan_dir / RESERVE_TARGETS_FILE)[
            "document_locator_key"
        ].to_pylist()
    )
    assert active.isdisjoint(reserve)


def test_a_zero_reserve_writes_no_reserve_file(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]), _policy(reserve_size=0), artifacts_root
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert not (plan_dir / RESERVE_TARGETS_FILE).exists()
    assert meta["reserve_count"] == 0
