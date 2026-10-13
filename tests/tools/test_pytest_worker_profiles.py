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
        lambda _selectors: ([test_file], "scope-v1", fingerprints),
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
        lambda _selectors: ([test_file], "scope-v1", fingerprints),
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


def test_case_estimate_uses_file_then_folder_distribution() -> None:
    file = Path("tests/pipelines/test_new.py")
    cases = {
        "tests/pipelines/test_old.py::test_a": {
            "file": "tests/pipelines/test_old.py",
            "folder": "pipelines",
            "duration": 2.0,
        },
        "tests/pipelines/test_other.py::test_b": {
            "file": "tests/pipelines/test_other.py",
            "folder": "pipelines",
            "duration": 4.0,
        },
    }
    assert profiles._case_estimate(file, cases) == 3.0
    cases[next(iter(cases))]["file"] = file.as_posix()
    assert profiles._case_estimate(file, cases) == 2.0


def test_inventory_delta_preserves_unchanged_cases_and_estimates_new_cases(
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "tests" / "pipelines" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_old(): pass\ndef test_new(): pass\n")
    unchanged = f"{test_file.as_posix()}::test_old"
    added = f"{test_file.as_posix()}::test_new"
    removed = "tests/pipelines/test_removed.py::test_removed"
    prior = {
        "cases": {
            unchanged: {
                "file": test_file.as_posix(),
                "folder": "pipelines",
                "fingerprint": "current",
                "duration": 3.0,
                "estimated": False,
            },
            removed: {
                "file": "tests/pipelines/test_removed.py",
                "folder": "pipelines",
                "fingerprint": "old",
                "duration": 8.0,
                "estimated": False,
            },
        }
    }

    cases = profiles._current_cases(
        [unchanged, added], [test_file], prior, {test_file.as_posix(): "current"}
    )

    assert cases[unchanged]["duration"] == 3.0
    assert cases[added]["duration"] == 3.0
    assert cases[added]["estimated"] is True
    assert removed not in cases


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
        profiles, "scope_inventory", lambda _selectors: ([], "same", {})
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


def test_scope_write_preserves_unrelated_profiles(tmp_path: Path) -> None:
    cache_path = tmp_path / "workers.json"
    profiles._write_profile(cache_path, "folder:tests/a", {"selected_workers": 2})
    profiles._write_profile(cache_path, "folder:tests/b", {"selected_workers": 4})
    cache = profiles.load_cache(cache_path)
    assert cache is not None
    assert cache["profiles"]["folder:tests/a"]["selected_workers"] == 2
    assert cache["profiles"]["folder:tests/b"]["selected_workers"] == 4


def test_resume_candidate_list_excludes_completed_trials() -> None:
    assert profiles.adaptive_worker_candidates([0, 2, 4, 8], 8, {0, 2, 4}) == [8]
