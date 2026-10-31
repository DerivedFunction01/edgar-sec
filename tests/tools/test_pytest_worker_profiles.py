from __future__ import annotations

import time
from pathlib import Path

import edgar_sec.tools.pytest_worker_profiles as profiles
from edgar_sec.tools.worker_profile_inventory import scope_key


def test_adaptive_seeds_include_model_and_coarse_tiers() -> None:
    assert profiles._seed_workers(
        {
            "n_max": 100,
            "work_total": 100,
            "c_w": 0.1,
            "n_crossover": 1,
            "hardware_cap": 16,
        },
        100,
        16,
        [],
    ) == [0, 2, 16]
    assert profiles.adaptive_worker_candidates([0, 2, 4], 16, {0, 2, 4}) == [8, 16]
    assert profiles.adaptive_worker_candidates([0, 2], 1) == [0]


def test_four_worker_model_seed_does_not_omit_eight_worker_tier(monkeypatch) -> None:
    monkeypatch.setattr(profiles, "_model_candidate", lambda *_args: 4)
    seeds = profiles._seed_workers({}, 100, 16, [])
    assert 4 in seeds
    assert 8 in profiles.adaptive_worker_candidates(seeds, 16)


def test_refinement_continues_above_regressing_four_worker_probe() -> None:
    assert profiles._next_refinement(8, {0, 2, 4, 8, 16}, 16) == 12


def test_aggregate_search_prunes_serial_and_two_worker_probes(
    monkeypatch, tmp_path: Path
) -> None:
    test_file = Path("tests/domain/test_sample.py")
    nodeids = [f"{test_file.as_posix()}::test_{index}" for index in range(4)]
    fingerprints = {test_file.as_posix(): "source-v1"}
    calls = []
    monkeypatch.setattr(
        profiles,
        "scope_inventory",
        lambda _selectors: ([test_file], "scope-v1", fingerprints, "context-v1"),
    )
    monkeypatch.setattr(
        profiles, "collect_test_nodeids", lambda _selectors: (nodeids, 0.01)
    )
    monkeypatch.setattr(profiles, "_resource_ceiling", lambda: 8)
    monkeypatch.setattr(profiles, "_model_candidate", lambda *_args: 4)

    def probe(_selectors: list[str], workers: int) -> dict:
        calls.append(workers)
        wall_seconds = 90.0 if workers == 8 else 100.0
        return {
            "wall_seconds": wall_seconds,
            "cases": [
                {
                    "nodeid": nodeid,
                    "duration": 100.0,
                    "phases": {"call": 100.0},
                }
                for nodeid in nodeids
            ],
        }

    monkeypatch.setattr(profiles, "_run_scope_probe", probe)
    profile = profiles._calibrate_scope(["tests/domain"], {}, tmp_path / "workers.json")

    assert profile["selected_workers"] == 8
    assert profile["probe_baseline_cases"] == {
        nodeid: test_file.as_posix() for nodeid in nodeids
    }
    assert 0 not in calls and 2 not in calls
    assert profile["trials"]["0"][0]["status"] == "pruned"
    assert profile["trials"]["2"][0]["status"] == "pruned"


def test_upward_search_stops_after_midpoint_exceeds_baseline_tolerance(
    monkeypatch, tmp_path: Path
) -> None:
    test_file = Path("tests/domain/test_sample.py")
    nodeids = [f"{test_file.as_posix()}::test_{index}" for index in range(4)]
    fingerprints = {test_file.as_posix(): "source-v1"}
    calls = []
    monkeypatch.setattr(
        profiles,
        "scope_inventory",
        lambda _selectors: ([test_file], "scope-v1", fingerprints, "context-v1"),
    )
    monkeypatch.setattr(
        profiles, "collect_test_nodeids", lambda _selectors: (nodeids, 0.01)
    )
    monkeypatch.setattr(profiles, "_resource_ceiling", lambda: 16)
    monkeypatch.setattr(profiles, "_model_candidate", lambda *_args: 16)

    def probe(_selectors: list[str], workers: int) -> dict:
        calls.append(workers)
        wall_seconds = {4: 100.0, 8: 120.0, 12: 130.0}[workers]
        return {
            "wall_seconds": wall_seconds,
            "cases": [
                {
                    "nodeid": nodeid,
                    "duration": 100.0,
                    "phases": {"call": 100.0},
                }
                for nodeid in nodeids
            ],
        }

    monkeypatch.setattr(profiles, "_run_scope_probe", probe)
    profile = profiles._calibrate_scope(
        ["tests/domain"], {}, tmp_path / "workers.duckdb"
    )

    assert calls == [4, 8, 12]
    assert profile["trials"]["16"][0]["status"] == "pruned"
    assert profile["trials"]["16"][0]["source"] == "upward_regression"


def test_failed_normal_run_is_stored_without_case_timings(
    monkeypatch, tmp_path: Path
) -> None:
    selectors = ["tests/domain/test_sample.py"]
    monkeypatch.setattr(
        profiles,
        "scope_inventory",
        lambda _selectors: ([], "fp", {}, "context-v1"),
    )
    cache_path = tmp_path / "workers.duckdb"

    profiles.record_normal_run(
        selectors,
        2,
        3.5,
        tmp_path / "missing-profile.json",
        cache_path,
        source="fast_baseline",
        status="failed",
    )

    profile = profiles.load_profiles(cache_path)[scope_key(selectors)]
    trial = profile["trials"]["2"][0]
    assert trial["wall_seconds"] == 3.5
    assert trial["status"] == "failed"
    assert trial["source"] == "fast_baseline"
    assert trial["item_work"] is None


def test_measured_trials_choose_eight_workers_despite_four_regressing() -> None:
    profile = {
        "trials": {
            "0": [{"wall_seconds": 100}],
            "2": [{"wall_seconds": 70}],
            "4": [{"wall_seconds": 110}],
            "8": [{"wall_seconds": 50}],
        }
    }
    assert profiles._profile_worker(profile) == 8


def test_adjusted_estimates_keep_shared_overhead_unscaled() -> None:
    profile = {
        "trials": {
            "0": [{"wall_seconds": 10.0, "item_work": 10.0, "shared_seconds": 0.0}],
            "2": [{"wall_seconds": 12.0, "item_work": 2.0, "shared_seconds": 10.0}],
        }
    }
    assert profiles._adjusted_recommendation(profile, 5.0) == 0


def test_fast_scope_selection_warm_starts_on_inventory_change(monkeypatch) -> None:
    old_file = Path("tests/domain/test_old.py")
    new_file = Path("tests/domain/test_new.py")
    old_nodeids = [f"{old_file.as_posix()}::test_{index}" for index in range(10)]
    new_nodeids = [f"{new_file.as_posix()}::test_{index}" for index in range(2)]
    context = "context-v1"
    prior = {
        "inventory_fingerprint": "old-inventory",
        "context_fingerprint": context,
        "cases": {
            nodeid: {
                "file": old_file.as_posix(),
                "folder": "domain",
                "fingerprint": "old-file",
                "duration": 10.0,
                "estimated": False,
            }
            for nodeid in old_nodeids
        },
        "trials": {
            "4": [
                {
                    "wall_seconds": 100.0,
                    "item_work": 100.0,
                    "shared_seconds": 0.0,
                    "inventory_fingerprint": "old-inventory",
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
                    "inventory_fingerprint": "old-inventory",
                    "context_fingerprint": context,
                    "status": "ok",
                    "at": 2.0,
                }
            ],
        },
    }
    monkeypatch.setattr(
        profiles,
        "collect_test_nodeids",
        lambda _selectors: ([*old_nodeids, *new_nodeids], 0.01),
    )

    workers, source, _ = profiles.choose_fast_workers_for_scope(
        prior,
        ["tests/domain"],
        16,
        "new-inventory",
        context,
        [old_file, new_file],
        {old_file.as_posix(): "old-file", new_file.as_posix(): "new-file"},
    )

    assert workers == 8
    assert source == "warm_forecast"


def test_fresh_profile_cache_hit_skips_collection(monkeypatch, tmp_path: Path) -> None:
    key = scope_key(["tests/domain"])
    profile = {
        "updated_at": time.time(),
        "inventory_fingerprint": "same",
        "selected_workers": 4,
    }
    monkeypatch.setattr(
        profiles, "load_cache", lambda _path: {"profiles": {key: profile}}
    )
    monkeypatch.setattr(
        profiles,
        "scope_inventory",
        lambda _selectors: ([], "same", {}, "context-v1"),
    )
    monkeypatch.setattr(
        profiles,
        "collect_test_nodeids",
        lambda _selectors: (_ for _ in ()).throw(
            AssertionError("unexpected collection")
        ),
    )
    assert (
        profiles.select_workers(["tests/domain"], cache_path=tmp_path / "cache.json")
        == 4
    )


def test_material_node_churn_reprobes_instead_of_reusing_scaled_estimate(
    monkeypatch, tmp_path: Path
) -> None:
    test_file = Path("tests/domain/test_sample.py")
    old_nodeids = [f"{test_file.as_posix()}::test_{index}" for index in range(10)]
    current_nodeids = [*old_nodeids[:8], f"{test_file.as_posix()}::test_added_a"]
    baseline = {nodeid: test_file.as_posix() for nodeid in old_nodeids}
    prior = {
        "updated_at": time.time(),
        "selected_workers": 2,
        "inventory_fingerprint": "old-scope",
        "probe_baseline_cases": baseline,
        "cases": {
            nodeid: {
                "file": test_file.as_posix(),
                "folder": "domain",
                "fingerprint": "old-file",
                "duration": 1.0,
                "estimated": False,
            }
            for nodeid in old_nodeids
        },
        "trials": {
            "2": [
                {
                    "wall_seconds": 5.0,
                    "item_work": 10.0,
                    "shared_seconds": 0.0,
                    "inventory_fingerprint": "old-scope",
                    "status": "ok",
                }
            ]
        },
    }
    key = scope_key([test_file.as_posix()])
    monkeypatch.setattr(
        profiles, "load_cache", lambda _path: {"profiles": {key: prior}}
    )
    monkeypatch.setattr(
        profiles,
        "scope_inventory",
        lambda _selectors: (
            [test_file],
            "new-scope",
            {test_file.as_posix(): "new-file"},
            "context-v1",
        ),
    )
    monkeypatch.setattr(
        profiles,
        "collect_test_nodeids",
        lambda _selectors: (current_nodeids, 0.01),
    )
    probes = []
    monkeypatch.setattr(
        profiles,
        "_calibrate_scope",
        lambda *args, **kwargs: (
            probes.append((args, kwargs)) or {"selected_workers": 4}
        ),
    )

    selected = profiles.select_workers(
        [test_file.as_posix()], cache_path=tmp_path / "workers.duckdb"
    )

    assert selected == 4
    assert probes


def test_scope_write_preserves_unrelated_profiles(tmp_path: Path) -> None:
    cache_path = tmp_path / "workers.json"
    baseline = {"tests/a/test_one.py::test_one": "tests/a/test_one.py"}
    profiles._write_profile(
        cache_path,
        "folder:tests/a",
        {"selected_workers": 2, "probe_baseline_cases": baseline},
    )
    profiles._write_profile(cache_path, "folder:tests/b", {"selected_workers": 4})
    cache = profiles.load_cache(cache_path)
    assert cache is not None
    assert cache["profiles"]["folder:tests/a"]["selected_workers"] == 2
    assert cache["profiles"]["folder:tests/b"]["selected_workers"] == 4
    loaded = profiles.load_profiles(cache_path)["folder:tests/a"]
    assert loaded["probe_baseline_cases"] == baseline


def test_changed_case_fingerprint_does_not_keep_old_call_time() -> None:
    test_file = Path("tests/domain/test_sample.py")
    nodeid = f"{test_file.as_posix()}::test_one"
    profile = {
        "cases": {
            nodeid: {
                "fingerprint": "old",
                "call_seconds": 1.0,
            }
        }
    }

    profiles._merge_case_timings(
        profile,
        [{"nodeid": nodeid, "duration": 3.0, "phases": {"call": 3.0}}],
        [test_file],
        {test_file.as_posix(): "new"},
    )

    assert profile["cases"][nodeid]["call_seconds"] == 3.0


def test_resume_candidate_list_excludes_completed_trials() -> None:
    assert profiles.adaptive_worker_candidates([0, 2, 4, 8], 8, {0, 2, 4}) == [8]
