from __future__ import annotations

import edgar_sec.tools.worker_profile_search as profile_search


def test_candidates_run_in_ascending_worker_order() -> None:
    assert profile_search.ordered_candidates([0, 2, 4, 8, 16]) == [4, 8, 16, 2, 0]


def test_upward_regression_uses_best_lower_worker_and_error_margin() -> None:
    profile = {
        "trials": {
            "4": [{"wall_seconds": 100, "inventory_fingerprint": "same"}],
            "8": [{"wall_seconds": 120, "inventory_fingerprint": "same"}],
            "12": [{"wall_seconds": 126, "inventory_fingerprint": "same"}],
        }
    }

    assert profile_search.upward_regression(profile, "same") == (12, 4, 100, 126)


def test_lower_bound_prunes_only_baselines_that_cannot_beat_incumbent() -> None:
    cases = {str(index): {"call_seconds": 100.0} for index in range(4)}
    assert profile_search.should_prune_baseline(0, cases, 100.0) == (True, 400.0)
    assert profile_search.should_prune_baseline(2, cases, 100.0) == (True, 200.0)
    cases["3"]["call_seconds"] = 50.0
    assert profile_search.should_prune_baseline(2, cases, 150.0) == (False, 175.0)
    assert profile_search.should_prune_baseline(0, {"unknown": {}}, 1.0) == (
        False,
        None,
    )
