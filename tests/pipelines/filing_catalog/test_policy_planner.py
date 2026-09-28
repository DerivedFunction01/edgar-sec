"""Tests for the policy-scope plan: quota selection published as a plan bundle.

Stage A's deterministic plan slices on four filters and publishes eight locator
columns. These tests cover the Stage B bundle: the 18-column locator
projection, the reserve pool, the recorded policy, and the immutability and
conflict semantics that make the bundle a work order rather than a cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_BASE_COLUMNS,
    LOCATOR_POLICY_COLUMNS,
)
from edgar_sec.engine.selection.policy import EraBand, SeedFiler, SelectionPolicy
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_NAME,
    REQUIRED_PLAN_FILES,
    RESERVE_TARGETS_NAME,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planner import (
    SCOPE_DETERMINISTIC,
    SCOPE_POLICY,
    plan,
    plan_policy,
)
from edgar_sec.pipelines.filing_catalog.publication import (
    PlanConflictError,
    plan_bundle_complete,
)


def _policy(**overrides: object) -> SelectionPolicy:
    base: dict[str, object] = {
        "corpus_id": "policy_corpus",
        "forms": ["10-K", "8-K"],
        "era_bands": [EraBand(name="modern", start_year=2010)],
        "base_content_units": 3,
        "reserve_size": 1,
        "seed_cik_path": "__absent__",
    }
    base.update(overrides)
    return SelectionPolicy(**base)  # type: ignore[arg-type]


def test_policy_plan_publishes_a_complete_bundle(
    catalog_snapshot: tuple[dict[str, object], Path], tmp_path: Path
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    policy = _policy()
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)

    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert plan_bundle_complete(plan_dir)
    for name in REQUIRED_PLAN_FILES:
        assert (plan_dir / name).is_file()


def _artifacts_root(catalog_snapshot: tuple[dict[str, object], Path]) -> Path:
    """The artifacts root the catalog fixture was materialized into."""
    _, snapshot_dir = catalog_snapshot
    # .../artifacts/filing_catalog/<catalog_id> -> .../artifacts
    return snapshot_dir.parent.parent


def test_policy_plan_locator_groups_are_the_eighteen_column_schema(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    """A Stage B bundle must carry the stratification dimensions a consumer
    audits a sample with, not just the identity triple Stage A emits."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    schema = pq.read_schema(plan_dir / LOCATOR_GROUPS_NAME)
    assert list(schema.names) == list(LOCATOR_POLICY_COLUMNS)
    assert len(schema.names) == 18
    assert set(LOCATOR_BASE_COLUMNS) <= set(schema.names)


def test_stage_a_locator_schema_stays_narrow(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    """A consumer must not be able to assume 18 columns in a deterministic plan."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    meta = plan(str(manifest["catalog_id"]), artifacts_root, forms=("10-K",))
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    schema = pq.read_schema(plan_dir / LOCATOR_GROUPS_NAME)
    assert list(schema.names) == list(LOCATOR_BASE_COLUMNS)
    assert len(schema.names) == 8


def test_policy_plan_partitions_targets_by_form(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    assert set(meta["counts"]) == {"10-K", "8-K"}
    for form, count in meta["counts"].items():
        partition = plan_dir / "targets" / f"form={form}" / "data.parquet"
        assert partition.is_file()
        assert pq.read_metadata(partition).num_rows == count
    assert meta["selected_rows"] == sum(meta["counts"].values())


def test_policy_plan_records_the_policy_that_produced_it(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    """A plan must be self-describing: the quota profile is part of the record."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    policy = _policy(base_content_units=2)
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)

    assert meta["scope"] == SCOPE_POLICY
    assert meta["policy_fingerprint"] == policy.policy_fingerprint
    assert meta["policy_corpus"] == policy.corpus_id
    assert meta["target_units"] == 2
    assert meta["parent_plan_id"] is None
    assert meta["seed_fingerprint"]
    assert SelectionPolicy.from_dict(meta["selection_policy"]).policy_fingerprint == (
        policy.policy_fingerprint
    )


def test_policy_plan_writes_a_reserve_pool(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    reserve = plan_dir / RESERVE_TARGETS_NAME
    assert reserve.is_file()
    assert pq.read_metadata(reserve).num_rows == meta["reserve_count"]


def test_reserve_is_disjoint_from_the_active_locators(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    active = set(
        pq.read_table(plan_dir / LOCATOR_GROUPS_NAME)[
            "document_locator_key"
        ].to_pylist()
    )
    reserve = set(
        pq.read_table(plan_dir / RESERVE_TARGETS_NAME)[
            "document_locator_key"
        ].to_pylist()
    )
    assert active.isdisjoint(reserve)


def test_a_zero_reserve_writes_no_reserve_file(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    meta = plan_policy(
        str(manifest["catalog_id"]), _policy(reserve_size=0), artifacts_root
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert not (plan_dir / RESERVE_TARGETS_NAME).exists()
    assert meta["reserve_count"] == 0


def test_policy_plan_id_is_content_derived_and_stable(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    """The same catalog and policy must resolve to the same bundle, not fork one."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    policy = _policy()
    first = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    second = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    assert first["plan_id"] == second["plan_id"]


def test_a_different_policy_publishes_a_different_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    baseline = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    other = plan_policy(
        str(manifest["catalog_id"]),
        _policy(base_content_units=2),
        artifacts_root,
    )
    assert baseline["plan_id"] != other["plan_id"]


def test_policy_and_deterministic_scopes_never_collide(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    """Both scopes publish locator_groups.parquet under a content-derived id."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    deterministic = plan(str(manifest["catalog_id"]), artifacts_root, forms=("10-K",))
    policy = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    assert deterministic["plan_id"] != policy["plan_id"]
    assert deterministic["scope"] == SCOPE_DETERMINISTIC


def test_an_incomplete_bundle_is_a_conflict_not_an_overwrite(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    """A published bundle is immutable, even when it is damaged."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    policy = _policy()
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    (plan_dir / LOCATOR_GROUPS_NAME).unlink()

    with pytest.raises(PlanConflictError, match="incomplete plan bundle"):
        plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)


def test_selection_report_carries_the_quota_evidence(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    """The report is what a reader checks to see the sample is actually balanced."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    report = json.loads(
        (plan_dir / "selection_report.json").read_text(encoding="utf-8")
    )

    assert report["scope"] == SCOPE_POLICY
    assert report["target_units"] == meta["target_units"]
    assert report["active_locators_count"] == meta["unique_locators_count"]
    assert report["unique_company_families"] >= 1
    assert "underfilled_floors" in report
    # The full coverage distribution is deliberately excluded: it is per
    # dimension and would dwarf the plan document it is embedded in.
    assert "coverage_distributions" not in report


def test_an_unsatisfiable_floor_is_reported_in_the_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    """A published plan must not assert a quota it never met."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    policy = _policy(floors={"era": {"prehistoric": 2}})
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    assert meta["underfilled_floors"]["era"]["prehistoric"]["deficit"] == 2


def test_seed_filers_are_recorded_in_the_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    seeds = {"0000000019": SeedFiler(cik="0000000019", seed_group="anchor")}
    policy = _policy()
    with_seeds = plan_policy(
        str(manifest["catalog_id"]), policy, artifacts_root, seed_filers=seeds
    )
    without = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    assert with_seeds["seed_fingerprint"] != without["seed_fingerprint"]
    assert with_seeds["plan_id"] != without["plan_id"]


def test_policy_plan_rejects_a_policy_with_no_forms(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_snapshot)
    policy = _policy()
    policy.forms = []
    with pytest.raises(ValueError, match="at least one form"):
        plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)


def test_plan_rejects_an_unsafe_catalog_reference(
    catalog_snapshot: tuple[dict[str, object], Path],
) -> None:
    artifacts_root = _artifacts_root(catalog_snapshot)
    with pytest.raises(ValueError, match="unsafe identifier"):
        plan_policy("../../etc", _policy(), artifacts_root)
