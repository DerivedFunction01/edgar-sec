"""Facade battery: bundle loader and face-value check specimens."""

from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.discovery.cohort import (
    canonical_probe_cohort_path,
    load_seed_cohort,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import bundle_dir_for
from edgar_sec.tools.xbrl_eval.facade_battery import (
    XBRL_FIXTURES,
    _catalog_entries,
    _face_value_check,
    _mode_violation,
    check_statement_views,
    cohort_folders,
    run_battery,
)

_MSFT = "msft_2024_10k"


def test_cohort_folders_subset_and_order() -> None:
    """Folder enumeration is name-ordered and honours the subset filter."""
    assert cohort_folders("seed", [_MSFT]) == [_MSFT]
    assert "bac_2011_10k" in cohort_folders("vintage")


def test_face_value_check_msft_revenue() -> None:
    """MSFT revenue is a face value at the latest period; a wrong sum is not."""
    xbrl = Xbrl.from_bundle(XBRL_FIXTURES / "seed" / _MSFT, load_domain_taxonomy())
    entry = next(
        entry
        for entry in _catalog_entries(xbrl)
        if entry.family == "IncomeStatement" and entry.title == "Income Statements"
    )
    view = xbrl.statements.view(entry.role_uri, mode="standard")
    found = _face_value_check(view, 245_122_000_000.0)
    assert found["found"] is True
    assert found["period"] == "2024-06-30"
    missed = _face_value_check(view, 245_122_001_000.0)
    assert missed["found"] is False
    assert missed["nearest"]["value"] == 245_122_000_000.0
    assert missed["nearest"]["difference"] == 1000.0


def _probe_xbrl(folder: str) -> Xbrl:
    registry = canonical_probe_cohort_path()
    seed = next(
        seed
        for seed in load_seed_cohort(registry)
        if bundle_dir_for(str(seed.accession), registry).name == folder
    )
    return Xbrl.from_bundle(
        bundle_dir_for(str(seed.accession), registry), load_domain_taxonomy()
    )


def test_face_total_check_anchors_at_served_span_aapl_10q() -> None:
    """A YTD-served cash-flow total is found on the face at its YTD period."""
    views = check_statement_views(_probe_xbrl("aapl_2026_10q"))
    check = next(c for c in views["face_totals"] if c["family"] == "CashFlow")
    assert check["status"] == "found"
    assert check["period"] == "2026-06-27 (YTD_3Q)"


def test_face_total_check_asx_net_income_ties_to_face() -> None:
    """ASX net income serves the standard bottom line the face carries."""
    views = check_statement_views(_probe_xbrl("asx_2023_20f"))
    check = next(c for c in views["face_totals"] if c["metric"] == "net_income")
    assert check["status"] == "found"


def test_face_total_check_whk_net_income_ties_to_face() -> None:
    """WHK net income roots on the revenue-summing face, not the O&G schedule."""
    views = check_statement_views(_probe_xbrl("whk_2026_s1"))
    check = next(c for c in views["face_totals"] if c["metric"] == "net_income")
    assert check["status"] == "found"


def test_face_total_check_tcbx_net_income_ties_to_face() -> None:
    """TCBX keeps its attributable bottom line; its revenue head sits in the CF tree."""
    views = check_statement_views(_probe_xbrl("tcbx_2022_s4"))
    check = next(c for c in views["face_totals"] if c["metric"] == "net_income")
    assert check["status"] == "found"
    assert check["expected"] == 2087000.0


def test_mode_violation_relation() -> None:
    """Only a complete count set can violate summary <= standard <= detailed."""
    assert _mode_violation({}) is False
    assert _mode_violation({"summary": 5, "standard": 24, "detailed": 38}) is False
    assert _mode_violation({"summary": 30, "standard": 24, "detailed": 38}) is True


def _without_seconds(obj: Any) -> Any:
    """Recursively drop the per-filing timing field from a report fragment."""
    if isinstance(obj, dict):
        return {k: _without_seconds(v) for k, v in obj.items() if k != "seconds"}
    if isinstance(obj, list):
        return [_without_seconds(v) for v in obj]
    return obj


def test_pool_path_matches_sequential() -> None:
    """The workers=2 pool path returns the sequential records, peer pass included."""
    folders = ["msft_2024_10k", "jpm_2024_10k"]
    sequential = run_battery(["seed"], folders, workers=1)["cohorts"]["seed"]
    pooled = run_battery(["seed"], folders, workers=2)["cohorts"]["seed"]
    assert _without_seconds(pooled["filings"]) == _without_seconds(
        sequential["filings"]
    )
    assert pooled["summary"] == sequential["summary"]
    peers = {
        folder: record["surfaces"]["peer_search"]
        for folder, record in pooled["filings"].items()
    }
    assert peers["msft_2024_10k"]["peer"] == "jpm_2024_10k"
    assert peers["jpm_2024_10k"]["peer"] == "msft_2024_10k"
    assert all(record["status"] == "ok" for record in peers.values())


def test_extended_factories_registered_in_battery_and_driver() -> None:
    """Plan/fund factories stay wired into both standing surfaces."""
    from edgar_sec.tools.xbrl_eval.facade_battery import (
        COHORT_NAMES,
        _STATEMENT_CALLS,
    )
    from edgar_sec.tools.xbrl_eval.statement_view_driver import STATEMENT_FACTORIES

    for name in (
        "plan_net_assets",
        "plan_changes",
        "fund_assets_liabilities",
        "fund_operations",
    ):
        assert name in _STATEMENT_CALLS
        assert name in STATEMENT_FACTORIES
    assert "probe" in COHORT_NAMES
    assert len(cohort_folders("probe")) == 90
