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


def test_fast_policy_ignores_trials_from_another_inventory() -> None:
    selectors = ["tests/domain/test_small.py::test_one"]
    profile = {
        "trials": {
            "0": [{"wall_seconds": 10.0, "inventory_fingerprint": "old"}],
            "2": [{"wall_seconds": 1.0, "inventory_fingerprint": "old"}],
        }
    }

    assert profile_search.choose_fast_workers(
        profile, selectors, 8, inventory_fingerprint="new"
    ) == (0, "fast_baseline", "fast policy; selector size hint=1")
    profile["trials"]["0"].append(
        {"wall_seconds": 12.0, "inventory_fingerprint": "new"}
    )
    assert (
        profile_search.choose_fast_workers(
            profile, selectors, 8, inventory_fingerprint="new"
        )[0]
        == 2
    )


def test_warm_policy_moves_one_tier_toward_larger_work_forecast() -> None:
    context = "same-machine"
    profile = {
        "cases": {
            f"tests/domain/test_a.py::test_{index}": {
                "duration": 20.0,
                "estimated": False,
            }
            for index in range(10)
        },
        "trials": {
            "4": [
                {
                    "wall_seconds": 100.0,
                    "item_work": 100.0,
                    "shared_seconds": 0.0,
                    "inventory_fingerprint": "old",
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": 3.0,
                }
            ],
            "8": [
                {
                    "wall_seconds": 80.0,
                    "item_work": 100.0,
                    "shared_seconds": 0.0,
                    "inventory_fingerprint": "old",
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": 2.0,
                }
            ],
            "12": [
                {
                    "wall_seconds": 60.0,
                    "item_work": 100.0,
                    "shared_seconds": 0.0,
                    "inventory_fingerprint": "old",
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": 1.0,
                }
            ],
        },
    }

    workers, source, reason = profile_search.choose_fast_workers(
        profile,
        [f"tests/domain/test_a.py::test_{index}" for index in range(10)],
        16,
        inventory_fingerprint="new",
        context_fingerprint=context,
    )

    assert workers == 8
    assert source == "warm_forecast"
    assert "one tier" in reason


def test_warm_policy_moves_one_tier_down_for_smaller_work() -> None:
    context = "same-machine"
    profile = {
        "cases": {
            f"tests/domain/test_a.py::test_{index}": {
                "duration": 1.0,
                "estimated": False,
            }
            for index in range(10)
        },
        "trials": {
            str(worker): [
                {
                    "wall_seconds": seconds,
                    "item_work": 100.0,
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": observed_at,
                }
            ]
            for worker, seconds, observed_at in (
                (2, 10.0, 1.0),
                (4, 20.0, 2.0),
                (8, 30.0, 3.0),
            )
        },
    }

    assert profile_search.choose_fast_workers(
        profile,
        [f"tests/domain/test_a.py::test_{index}" for index in range(10)],
        8,
        inventory_fingerprint="new",
        context_fingerprint=context,
    ) == (4, "warm_forecast", "one tier toward work forecast n=2")


def test_warm_policy_clamps_prior_worker_to_new_resource_ceiling() -> None:
    context = "same-machine"
    profile = {
        "cases": {
            f"tests/domain/test_a.py::test_{index}": {
                "duration": 10.0,
                "estimated": False,
            }
            for index in range(10)
        },
        "trials": {
            "4": [
                {
                    "wall_seconds": 100.0,
                    "item_work": 100.0,
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": 1.0,
                }
            ],
            "8": [
                {
                    "wall_seconds": 80.0,
                    "item_work": 100.0,
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": 2.0,
                }
            ],
        },
    }

    assert (
        profile_search.choose_fast_workers(
            profile,
            [f"tests/domain/test_a.py::test_{index}" for index in range(10)],
            4,
            inventory_fingerprint="new",
            context_fingerprint=context,
        )[0]
        == 4
    )


def test_warm_policy_uses_last_worker_when_case_coverage_is_low() -> None:
    context = "same-machine"
    profile = {
        "cases": {
            f"tests/domain/test_a.py::test_{index}": {
                "duration": 10.0,
                "estimated": index >= 2,
            }
            for index in range(10)
        },
        "trials": {
            "4": [
                {
                    "wall_seconds": 100.0,
                    "item_work": 100.0,
                    "shared_seconds": 0.0,
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": 1.0,
                }
            ],
            "8": [
                {
                    "wall_seconds": 80.0,
                    "item_work": 100.0,
                    "shared_seconds": 0.0,
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": 2.0,
                }
            ],
        },
    }

    assert profile_search.choose_fast_workers(
        profile,
        [f"tests/domain/test_a.py::test_{index}" for index in range(10)],
        16,
        inventory_fingerprint="new",
        context_fingerprint=context,
    ) == (
        8,
        "warm_fallback",
        "reusing last compatible worker until more timings are available",
    )


def test_warm_fallback_resumes_tier_exploration_after_first_run() -> None:
    context = "same-machine"
    profile = {
        "cases": {
            f"tests/domain/test_{index}.py::test_one": {
                "duration": 1.0,
                "estimated": False,
            }
            for index in range(16)
        },
        "trials": {
            "4": [
                {
                    "wall_seconds": 10.0,
                    "item_work": 16.0,
                    "inventory_fingerprint": "new",
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": 2.0,
                }
            ]
        },
    }
    selectors = [f"tests/domain/test_{index}.py" for index in range(256)]

    assert (
        profile_search.choose_fast_workers(
            profile,
            selectors,
            8,
            inventory_fingerprint="new",
            context_fingerprint=context,
        )[0]
        == 8
    )


def test_warm_policy_probes_near_tied_adjacent_tier_once() -> None:
    context = "same-machine"
    cases = {
        f"tests/domain/test_a.py::test_{index}": {
            "duration": 10.0,
            "estimated": False,
        }
        for index in range(10)
    }
    profile = {
        "cases": cases,
        "trials": {
            "4": [
                {
                    "wall_seconds": 100.0,
                    "item_work": 100.0,
                    "context_fingerprint": context,
                    "inventory_fingerprint": "old",
                    "status": "ok",
                    "at": 2.0,
                }
            ],
            "8": [
                {
                    "wall_seconds": 110.0,
                    "item_work": 100.0,
                    "context_fingerprint": context,
                    "inventory_fingerprint": "old",
                    "status": "ok",
                    "at": 1.0,
                }
            ],
        },
    }
    selectors = [f"tests/domain/test_a.py::test_{index}" for index in range(10)]

    assert profile_search.choose_fast_workers(
        profile,
        selectors,
        8,
        inventory_fingerprint="new",
        context_fingerprint=context,
    ) == (
        8,
        "warm_challenger",
        "adjacent n=8 forecast is within 25% of n=4",
    )
    profile["trials"]["8"].append(
        {
            "wall_seconds": 110.0,
            "item_work": 100.0,
            "context_fingerprint": context,
            "inventory_fingerprint": "new",
            "status": "ok",
            "at": 3.0,
        }
    )
    assert (
        profile_search.choose_fast_workers(
            profile,
            selectors,
            8,
            inventory_fingerprint="new",
            context_fingerprint=context,
        )[0]
        == 4
    )


def test_warm_policy_ignores_trials_from_other_contexts() -> None:
    profile = {
        "cases": {
            f"tests/domain/test_a.py::test_{index}": {
                "duration": 10.0,
                "estimated": False,
            }
            for index in range(10)
        },
        "trials": {
            "8": [
                {
                    "wall_seconds": 1.0,
                    "item_work": 100.0,
                    "shared_seconds": 0.0,
                    "context_fingerprint": "old-context",
                    "inventory_fingerprint": "old-inventory",
                    "status": "ok",
                }
            ]
        },
    }

    assert (
        profile_search.choose_fast_workers(
            profile,
            [f"tests/domain/test_a.py::test_{index}" for index in range(10)],
            8,
            inventory_fingerprint="new-inventory",
            context_fingerprint="new-context",
        )[0]
        == 0
    )


def test_case_inventory_delta_counts_per_file_churn() -> None:
    baseline = {
        "tests/domain/test_a.py::test_keep": "tests/domain/test_a.py",
        "tests/domain/test_a.py::test_removed": "tests/domain/test_a.py",
        "tests/domain/test_b.py::test_stable": "tests/domain/test_b.py",
    }
    current = {
        "tests/domain/test_a.py::test_keep": "tests/domain/test_a.py",
        "tests/domain/test_a.py::test_added": "tests/domain/test_a.py",
        "tests/domain/test_b.py::test_stable": "tests/domain/test_b.py",
    }

    delta = profile_search.case_inventory_delta(baseline, current)

    assert delta["tests/domain/test_a.py"] == {
        "baseline": 2,
        "current": 2,
        "added": 1,
        "removed": 1,
    }
    assert delta["tests/domain/test_b.py"] == {
        "baseline": 1,
        "current": 1,
        "added": 0,
        "removed": 0,
    }
    assert profile_search.material_case_inventory_change(delta)


def test_case_inventory_delta_ignores_small_scope_churn() -> None:
    baseline = {
        f"tests/domain/test_a.py::test_{index}": "tests/domain/test_a.py"
        for index in range(100)
    }
    current = dict(baseline)
    del current["tests/domain/test_a.py::test_0"]
    current["tests/domain/test_a.py::test_added"] = "tests/domain/test_a.py"

    delta = profile_search.case_inventory_delta(baseline, current)

    assert not profile_search.material_case_inventory_change(delta)
