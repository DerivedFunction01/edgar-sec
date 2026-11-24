from __future__ import annotations

import edgar_sec.tools.workers.worker_profile_recommend as recommend
from edgar_sec.tools.workers.worker_profile_search import adaptive_worker_candidates


def test_adaptive_seeds_include_model_and_coarse_tiers() -> None:
    assert recommend._seed_workers(
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
    assert adaptive_worker_candidates([0, 2, 4], 16, {0, 2, 4}) == [8, 16]
    assert adaptive_worker_candidates([0, 2], 1) == [0]


def test_four_worker_model_seed_does_not_omit_eight_worker_tier(monkeypatch) -> None:
    monkeypatch.setattr(recommend, "_model_candidate", lambda *_args: 4)
    seeds = recommend._seed_workers({}, 100, 16, [])
    assert 4 in seeds
    assert 8 in adaptive_worker_candidates(seeds, 16)


def test_measured_trials_choose_eight_workers_despite_four_regressing() -> None:
    profile = {
        "trials": {
            "0": [{"wall_seconds": 100}],
            "2": [{"wall_seconds": 70}],
            "4": [{"wall_seconds": 110}],
            "8": [{"wall_seconds": 50}],
        }
    }
    assert recommend._profile_worker(profile) == 8


def test_adjusted_estimates_keep_shared_overhead_unscaled() -> None:
    profile = {
        "trials": {
            "0": [{"wall_seconds": 10.0, "item_work": 10.0, "shared_seconds": 0.0}],
            "2": [{"wall_seconds": 12.0, "item_work": 2.0, "shared_seconds": 10.0}],
        }
    }
    assert recommend._adjusted_recommendation(profile, 5.0) == 0
