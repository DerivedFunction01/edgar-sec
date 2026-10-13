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


def test_upward_regression_can_stop_after_two_workers() -> None:
    profile = {
        "trials": {
            "0": [{"wall_seconds": 100, "inventory_fingerprint": "same"}],
            "2": [{"wall_seconds": 126, "inventory_fingerprint": "same"}],
        }
    }

    assert profile_search.upward_regression(profile, "same") == (2, 0, 100, 126)


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


def test_fast_policy_progresses_across_runs_and_stops_after_regression() -> None:
    selectors = ["tests/domain/test_small.py::test_one"]
    profile = {"trials": {}}

    assert profile_search.choose_fast_workers(profile, selectors, 8) == (
        0,
        "fast_baseline",
        "fast policy; selector size hint=1",
    )
    profile["trials"]["0"] = [
        {"wall_seconds": 100, "status": "ok", "source": "fast_baseline"}
    ]
    assert profile_search.choose_fast_workers(profile, selectors, 8) == (
        2,
        "fast_exploration",
        "fast policy; selector size hint=1",
    )
    profile["trials"]["2"] = [
        {"wall_seconds": 120, "status": "ok", "source": "fast_exploration"}
    ]
    assert profile_search.choose_fast_workers(profile, selectors, 8)[0] == 4
    profile["trials"]["4"] = [
        {"wall_seconds": 130, "status": "ok", "source": "fast_exploration"}
    ]
    workers, source, reason = profile_search.choose_fast_workers(profile, selectors, 8)
    assert workers == 0
    assert source == "observed_history"
    assert "stopped above n=4" in reason


def test_fast_policy_uses_files_as_size_hint_and_caps_worker_counts(tmp_path) -> None:
    test_file = tmp_path / "test_example.py"
    test_file.write_text("def test_one(): pass\n", encoding="utf-8")
    assert profile_search.selector_size_hint([str(test_file)]) == 16
    assert profile_search.choose_fast_workers({}, [str(test_file)], 1)[0] == 0
    selectors = []
    for index in range(16):
        path = tmp_path / f"test_{index}.py"
        path.write_text("def test_one(): pass\n", encoding="utf-8")
        selectors.append(str(path))
    assert profile_search.selector_size_hint(selectors) == 256
    assert profile_search.choose_fast_workers({}, selectors, 3)[0] == 3
    assert profile_search.choose_fast_workers({}, selectors, 2)[0] == 2
