from __future__ import annotations

import logging
import sys
import argparse
import contextlib
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Any

PYTHON = sys.executable
logger = logging.getLogger(__name__)
DEFAULT_GAMMA = 0.76
CACHE_VERSION = 4
CACHE_EXPIRY_DAYS = 30
PROBE_TIMEOUT_SECONDS = 600


def detect_hardware_topology() -> tuple[int, int]:
    logical = os.cpu_count() or 1
    physical = logical
    try:
        import psutil

        physical = max(1, psutil.cpu_count(logical=False) or logical)
        logical = max(1, psutil.cpu_count(logical=True) or logical)
    except ImportError:
        if logical > 4:
            physical = max(1, logical // 2)
    return physical, logical


def default_cache_path(repo_root: pathlib.Path) -> pathlib.Path:
    from edgar_sec.foundation.checks.lineage import (
        default_cache_path as lineage_cache_path,
    )

    return lineage_cache_path(repo_root).parent / "pytest_workers.duckdb"


def load_cache(cache_path: pathlib.Path) -> dict[str, Any] | None:
    try:
        from edgar_sec.tools.profile_storage import load_machine

        machine = load_machine(cache_path)
        from edgar_sec.tools.profile_storage import load_profiles

        profiles = load_profiles(cache_path)
        if not machine and not profiles:
            return None
        return {
            "version": CACHE_VERSION,
            "machine_model": machine,
            "profiles": profiles,
        }
    except (OSError, KeyError, TypeError, ValueError, RuntimeError):
        return None


@contextlib.contextmanager
def _cache_lock(cache_path: pathlib.Path):
    lock_path = cache_path.with_suffix(cache_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        try:
            import fcntl
        except ImportError:
            yield
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_cache_unchecked(cache_path: pathlib.Path) -> dict[str, Any] | None:
    return load_cache(cache_path)


def _compatible_cache(cache_path: pathlib.Path) -> dict[str, Any]:
    return _read_cache_unchecked(cache_path) or {}


def save_cache(cache_path: pathlib.Path, results: dict[str, Any]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with _cache_lock(cache_path):
            from edgar_sec.tools.profile_storage import save_machine

            machine = results.get("machine_model", results)
            physical, logical = detect_hardware_topology()
            machine = {**machine, "physical_cores": physical, "logical_cores": logical}
            save_machine(cache_path, machine)
    except (OSError, TypeError, ValueError, RuntimeError):
        pass


def collect_test_nodeids(test_args: list[str]) -> tuple[list[str], float]:
    cmd = [
        PYTHON,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "--no-header",
        "--no-summary",
        "-p",
        "no:cacheprovider",
        *test_args,
    ]
    started = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(f"pytest collection failed: {result.stderr[-1500:]}")
    nodeids = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
        and not line.startswith("=")
        and not line.startswith("collected")
        and not re.match(r"^\d+ tests? collected\b", line.strip())
    ]
    if not nodeids:
        raise RuntimeError("no tests found")
    return nodeids, elapsed


def run_single_probe(
    target_count: int, workers: int, all_nodeids: list[str]
) -> dict[str, float]:
    cmd = [
        PYTHON,
        "-m",
        "pytest",
        "-q",
        "--no-header",
        "--no-summary",
        "-p",
        "no:cacheprovider",
    ]
    if workers >= 2:
        cmd.extend(["-n", str(workers)])
    cmd.extend(all_nodeids[:target_count])
    started = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(f"probe failed at n={workers}: {result.stderr[-1200:]}")
    return {"execution_seconds": elapsed, "total_seconds": elapsed}


def solve_two_point_parameters(
    w1: int, t1: float, w2: int, t2: float, gamma: float = DEFAULT_GAMMA
) -> tuple[float, float]:
    w1_g, w2_g = w1**gamma, w2**gamma
    w1_1g, w2_1g = w1 ** (1.0 + gamma), w2 ** (1.0 + gamma)
    denominator = w2_1g - w1_1g
    if abs(denominator) < 1e-6:
        return 1.0, 100.0
    worker_cost = max(0.01, (t2 * w2_g - t1 * w1_g) / denominator)
    work = max(1.0, t1 * w1_g - worker_cost * w1_1g)
    return worker_cost, work


def compute_optimal_workers(
    test_count: int,
    ref_tests: int,
    work_total: float,
    c_w: float,
    n_crossover: int,
    hardware_cap: int,
    gamma: float = DEFAULT_GAMMA,
) -> int:
    if test_count <= 0 or test_count < n_crossover:
        return 0
    scaled_work = work_total * (test_count / ref_tests)
    continuous = (gamma * scaled_work / c_w) ** (1.0 / (1.0 + gamma))
    workers = int(round(continuous))
    return min(hardware_cap, workers) if workers >= 2 else 0


def run_calibration(
    test_args: list[str],
    cache_path: pathlib.Path | None = None,
    repo_root: pathlib.Path | None = None,
    all_nodeids: list[str] | None = None,
) -> dict[str, Any]:
    logger.info("calibration started")
    physical, logical = detect_hardware_topology()
    if all_nodeids is None:
        all_nodeids, _ = collect_test_nodeids(test_args)
    count = len(all_nodeids)
    micro_count = min(128, max(32, count // 4)) if count > 64 else count
    half = max(2, physical // 2)
    if half == physical:
        half = max(2, physical - 1)
    probes = [
        ("serial", micro_count, 0),
        ("n=2", micro_count, 2),
        (f"n={half}", count, half),
        (f"n={physical}", count, physical),
    ]
    if logical > physical:
        probes.append((f"n={logical}", count, logical))
    values: dict[str, float] = {}
    for index, (label, target, workers) in enumerate(probes, 1):
        logger.info(
            "probe %d/%d running: %s (%d tests)", index, len(probes), label, target
        )
        values[label] = run_single_probe(target, workers, all_nodeids)["total_seconds"]
        logger.info(
            "probe %d/%d complete: %s; %d remaining",
            index,
            len(probes),
            label,
            len(probes) - index,
        )
    serial_micro = values["serial"]
    parallel_micro = values["n=2"]
    half_time = values[f"n={half}"]
    physical_time = values[f"n={physical}"]
    logical_time = physical_time
    smt_beneficial = False
    if logical > physical:
        logical_time = values[f"n={logical}"]
        smt_beneficial = logical_time < physical_time
    worker_cost, work = solve_two_point_parameters(
        half, half_time, physical, physical_time
    )
    serial_per_test = max(0.001, serial_micro / micro_count)
    spawn_delta = max(0.05, parallel_micro - serial_micro / 2)
    crossover = max(32, int(round(spawn_delta / (serial_per_test * 0.4))))
    ceiling = logical if smt_beneficial else physical
    recommendation = min(
        ceiling,
        max(
            2,
            int(
                round((DEFAULT_GAMMA * work / worker_cost) ** (1 / (1 + DEFAULT_GAMMA)))
            ),
        ),
    )
    result = {
        "n_max": count,
        "physical_cores": physical,
        "logical_cores": logical,
        "gamma": DEFAULT_GAMMA,
        "c_w": round(worker_cost, 4),
        "work_total": round(work, 2),
        "n_crossover": crossover,
        "smt_beneficial": smt_beneficial,
        "hardware_cap": ceiling,
        "recommended_full_suite_workers": recommendation,
        "raw_probes": {
            "micro_serial": serial_micro,
            "micro_w2": parallel_micro,
            "macro_half_phys": half_time,
            "macro_full_phys": physical_time,
            "macro_full_log": logical_time,
        },
    }
    final_path = cache_path or default_cache_path(repo_root or pathlib.Path.cwd())
    save_cache(final_path, {"machine_model": result})
    logger.info("calibration complete: selected n=%d", recommendation)
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Calibrate pytest worker scaling.")
    parser.add_argument("test_args", nargs="*", default=["tests"])
    parser.add_argument("--output")
    args = parser.parse_args()
    logger.info("Running pytest worker calibration with selectors: %s", args.test_args)
    run_calibration(
        args.test_args,
        cache_path=pathlib.Path(args.output) if args.output else None,
        repo_root=pathlib.Path.cwd(),
    )


if __name__ == "__main__":
    main()
