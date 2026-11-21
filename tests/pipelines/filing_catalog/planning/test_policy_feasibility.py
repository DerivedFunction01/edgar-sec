"""Advisory inventory feasibility in the selection report."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths
from edgar_sec.pipelines.filing_catalog.planning.policy import plan_policy
from edgar_sec.pipelines.filing_catalog.publication import plan_bundle_complete
from tests.pipelines.filing_catalog.planning.policy_support import (
    _artifacts_root,
    _policy,
)


def _advisory(plan_dir: Path) -> dict[str, object]:
    report = json.loads(
        (plan_dir / "selection_report.json").read_text(encoding="utf-8")
    )
    return dict(report["inventory_feasibility"])


def test_a_floor_policy_reports_inventory_feasibility(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """The report says whether the corpus could have met the quota, and by how much."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(floors={"era": {"modern": 2, "ancient": 5}}),
        artifacts_root,
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])

    advisory = _advisory(plan_dir)
    assert advisory["checked"] is True
    assert advisory["floors"]["era"]["modern"]["feasible"] is True
    assert advisory["floors"]["era"]["ancient"] == {
        "required": 5,
        "available": 0,
        "feasible": False,
        "deficit": 5,
    }
    assert advisory["infeasible_floors"] == ["ancient"]


def test_feasibility_is_advisory_and_does_not_fail_a_plan(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """A fresh plan publishes what the corpus could supply and records the shortfall."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(floors={"era": {"ancient": 500}}),
        artifacts_root,
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert _advisory(plan_dir)["infeasible_floors"] == ["ancient"]
    assert plan_bundle_complete(plan_dir)


def test_a_policy_with_no_quotas_skips_the_inventory(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """Nothing to predict, so the report says so instead of scanning."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(str(manifest["catalog_id"]), _policy(), artifacts_root)
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    assert _advisory(plan_dir) == {
        "checked": False,
        "reason": "policy declares no floors or composites",
    }


def test_a_composite_policy_reports_feasibility(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(composites=[{"filters": {"era": "modern"}, "min": 2}]),
        artifacts_root,
    )
    plan_dir = resolve_filing_catalog_paths(artifacts_root).plan_dir(meta["plan_id"])
    advisory = _advisory(plan_dir)
    assert advisory["checked"] is True
    assert advisory["composites"][0]["filters"] == {"era": "modern"}
    assert advisory["infeasible_composites"] == []


def test_a_sic_code_composite_is_accepted(
    catalog_snapshot: tuple[dict[str, object], Path],
    catalog_artifacts_root: Path,
) -> None:
    """sic_code is locator-grain, so a composite on it is a valid policy."""
    manifest, _ = catalog_snapshot
    artifacts_root = _artifacts_root(catalog_artifacts_root)
    meta = plan_policy(
        str(manifest["catalog_id"]),
        _policy(composites=[{"filters": {"sic_code": "3571"}, "min": 1}]),
        artifacts_root,
    )
    assert meta["plan_id"]
