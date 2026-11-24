from __future__ import annotations

import time
from pathlib import Path

import edgar_sec.tools.workers.pytest_worker_profiles as profiles
from edgar_sec.tools.workers.profile_storage import load_profiles
from edgar_sec.tools.workers.worker_profile_inventory import scope_key


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

    profile = load_profiles(cache_path)[scope_key(selectors)]
    trial = profile["trials"]["2"][0]
    assert trial["wall_seconds"] == 3.5
    assert trial["status"] == "failed"
    assert trial["source"] == "fast_baseline"
    assert trial["item_work"] is None


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
