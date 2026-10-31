from __future__ import annotations

from pathlib import Path

import check
import edgar_sec.tools.fast_pytest_worker_calibrator as calibrator
from check import worker_args
from edgar_sec.foundation.runtime import resources
from edgar_sec.tools.fast_pytest_worker_calibrator import (
    CACHE_EXPIRY_DAYS,
    collect_test_nodeids,
    compute_optimal_workers,
    load_cache,
    run_single_probe,
    save_cache,
)


def test_worker_args_avoid_xdist_for_zero_or_one() -> None:
    assert worker_args(0) == []
    assert worker_args(1) == []
    assert worker_args(2) == ["-n", "2"]


def test_memory_cap_of_one_returns_serial(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(resources, "available_memory_bytes", lambda: 1)
    monkeypatch.setattr(resources, "auto_worker_count", lambda _available: 1)
    monkeypatch.setattr(
        calibrator,
        "load_cache",
        lambda _path: {
            "c_w": 0.1,
            "work_total": 100,
            "n_crossover": 1,
            "hardware_cap": 8,
            "n_max": 100,
            "gamma": 0.76,
        },
    )
    monkeypatch.setattr(calibrator, "compute_optimal_workers", lambda *_args: 4)

    assert check.get_calibrated_workers(100, cache_path=tmp_path / "workers.json") == 0


def test_calibration_cache_expires(monkeypatch, tmp_path: Path) -> None:
    now = 1000.0
    monkeypatch.setattr(calibrator.time, "time", lambda: now)
    monkeypatch.setattr(calibrator, "detect_hardware_topology", lambda: (2, 2))
    cache_path = tmp_path / "workers.json"
    save_cache(
        cache_path,
        {"timestamp": now, "physical_cores": 2, "logical_cores": 2},
    )

    assert load_cache(cache_path) is not None

    monkeypatch.setattr(
        calibrator.time,
        "time",
        lambda: now + (CACHE_EXPIRY_DAYS + 1) * 86400,
    )
    assert load_cache(cache_path) is None


def test_xdist_is_not_selected_for_one_worker() -> None:
    assert (
        compute_optimal_workers(
            test_count=100,
            ref_tests=100,
            work_total=1,
            c_w=100,
            n_crossover=1,
            hardware_cap=8,
        )
        == 0
    )


def test_probe_runs_only_selected_nodeids() -> None:
    test_path = "tests/tools/test_fast_pytest_worker_calibrator.py"
    nodeids, _ = collect_test_nodeids([test_path])
    assert all("::" in nodeid for nodeid in nodeids)

    result = run_single_probe(1, 0, nodeids)

    assert result["total_seconds"] > 0
