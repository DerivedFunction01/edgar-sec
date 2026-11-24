from __future__ import annotations

from pathlib import Path

import edgar_sec.tools.workers.worker_profile_calibration as calibration
import edgar_sec.tools.workers.worker_profile_recommend as recommend
from edgar_sec.tools.workers.fast_pytest_worker_calibrator import load_cache
from edgar_sec.tools.workers.profile_storage import load_profiles


def test_aggregate_search_prunes_serial_and_two_worker_probes(
    monkeypatch, tmp_path: Path
) -> None:
    test_file = Path("tests/domain/test_sample.py")
    nodeids = [f"{test_file.as_posix()}::test_{index}" for index in range(4)]
    fingerprints = {test_file.as_posix(): "source-v1"}
    calls = []
    monkeypatch.setattr(
        calibration,
        "scope_inventory",
        lambda _selectors: ([test_file], "scope-v1", fingerprints, "context-v1"),
    )
    monkeypatch.setattr(
        calibration, "collect_test_nodeids", lambda _selectors: (nodeids, 0.01)
    )
    monkeypatch.setattr(calibration, "_resource_ceiling", lambda: 8)
    monkeypatch.setattr(calibration, "_model_candidate", lambda *_args: 4)
    monkeypatch.setattr(recommend, "_model_candidate", lambda *_args: 4)

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

    monkeypatch.setattr(calibration, "_run_scope_probe", probe)
    profile = calibration._calibrate_scope(
        ["tests/domain"], {}, tmp_path / "workers.json"
    )

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
        calibration,
        "scope_inventory",
        lambda _selectors: ([test_file], "scope-v1", fingerprints, "context-v1"),
    )
    monkeypatch.setattr(
        calibration, "collect_test_nodeids", lambda _selectors: (nodeids, 0.01)
    )
    monkeypatch.setattr(calibration, "_resource_ceiling", lambda: 16)
    monkeypatch.setattr(calibration, "_model_candidate", lambda *_args: 16)
    monkeypatch.setattr(recommend, "_model_candidate", lambda *_args: 16)

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

    monkeypatch.setattr(calibration, "_run_scope_probe", probe)
    profile = calibration._calibrate_scope(
        ["tests/domain"], {}, tmp_path / "workers.duckdb"
    )

    assert calls == [4, 8, 12]
    assert profile["trials"]["16"][0]["status"] == "pruned"
    assert profile["trials"]["16"][0]["source"] == "upward_regression"


def test_scope_write_preserves_unrelated_profiles(tmp_path: Path) -> None:
    cache_path = tmp_path / "workers.json"
    baseline = {"tests/a/test_one.py::test_one": "tests/a/test_one.py"}
    calibration._write_profile(
        cache_path,
        "folder:tests/a",
        {"selected_workers": 2, "probe_baseline_cases": baseline},
    )
    calibration._write_profile(cache_path, "folder:tests/b", {"selected_workers": 4})
    cache = load_cache(cache_path)
    assert cache is not None
    assert cache["profiles"]["folder:tests/a"]["selected_workers"] == 2
    assert cache["profiles"]["folder:tests/b"]["selected_workers"] == 4
    loaded = load_profiles(cache_path)["folder:tests/a"]
    assert loaded["probe_baseline_cases"] == baseline
