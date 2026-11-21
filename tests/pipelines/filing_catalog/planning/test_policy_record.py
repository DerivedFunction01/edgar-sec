"""The plan as a self-describing record: policy, report, and shortfalls."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.domain.filing_catalog.schemas import SCOPE_POLICY
from edgar_sec.engine.selection.policy import SelectionPolicy
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths
from edgar_sec.pipelines.filing_catalog.planning.policy import plan_policy
from tests.pipelines.filing_catalog.planning.policy_support import (
    _artifacts_root,
    _policy,
)


def test_policy_plan_records_the_policy_that_produced_it(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A plan must be self-describing: the quota profile is part of the record."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
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


def test_selection_report_carries_the_quota_evidence(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The report is what a reader checks to see the sample is actually balanced."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
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
    # Per-dimension coverage would dwarf the plan document it is embedded in.
    assert "coverage_distributions" not in report


def test_an_unsatisfiable_floor_is_reported_in_the_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A published plan must not assert a quota it never met."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    policy = _policy(floors={"era": {"prehistoric": 2}})
    meta = plan_policy(str(manifest["catalog_id"]), policy, artifacts_root)
    assert meta["underfilled_floors"]["era"]["prehistoric"]["deficit"] == 2
