"""Facade battery: bundle loader and face-value check specimens."""

from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.tools.facade_battery import (
    XBRL_FIXTURES,
    _catalog_entries,
    _face_value_check,
    _mode_violation,
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
