from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Any

PYTHON = sys.executable
DEFAULT_GAMMA = 0.76
CACHE_VERSION = 2
CACHE_EXPIRY_DAYS = 30


def detect_hardware_topology() -> tuple[int, int]:
    """
    Detects physical and logical CPU cores via psutil or system fallbacks.
    Returns:
        (physical_cores, logical_cores)
    """
    logical = os.cpu_count() or 1
    physical = logical

    try:
        import psutil

        detected_phys = psutil.cpu_count(logical=False)
        detected_log = psutil.cpu_count(logical=True)
        if detected_phys:
            physical = max(1, detected_phys)
        if detected_log:
            logical = max(1, detected_log)
    except ImportError:
        # Heuristic fallback if psutil is unavailable
        if logical > 4:
            physical = max(1, logical // 2)
        else:
            physical = logical
    return physical, logical


def default_cache_path(repo_root: pathlib.Path) -> pathlib.Path:
    """Return the calibration cache path under the artifacts transient/cache directory."""
    from edgar_sec.foundation.checks.lineage import (
        default_cache_path as lineage_cache_path,
    )

    return lineage_cache_path(repo_root).parent / "pytest_workers.json"


def load_cache(cache_path: pathlib.Path) -> dict[str, Any] | None:
    """Load existing calibration cache, returning None if missing or expired."""
    if not cache_path.is_file():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        if raw.get("version") != CACHE_VERSION:
            return None
        if time.time() - float(raw.get("timestamp", 0)) > CACHE_EXPIRY_DAYS * 86400:
            return None
        topology = (raw.get("physical_cores"), raw.get("logical_cores"))
        if topology != detect_hardware_topology():
            return None
        return raw
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_cache(cache_path: pathlib.Path, results: dict[str, Any]) -> None:
    """Save calibration cache atomically."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        raw = results.copy()
        raw["version"] = CACHE_VERSION
        encoded = json.dumps(raw, indent=2)
        tmp_target = cache_path.with_suffix(".tmp")
        tmp_target.write_text(encoded, encoding="utf-8")
        tmp_target.replace(cache_path)
    except (OSError, TypeError, ValueError):
        pass


def collect_test_nodeids(test_args: list[str]) -> tuple[list[str], float]:
    """Runs pytest --collect-only to gather all discoverable test node IDs."""
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
    ] + test_args

    sys.stderr.write(f"Collecting test IDs across: {' '.join(test_args)}...\n")
    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - t0

    if res.returncode != 0:
        sys.stderr.write(
            f"Collection failed after {elapsed:.2f}s:\n{res.stderr[-1500:]}\n"
        )
        raise RuntimeError("pytest collection failed")

    nodeids = [
        line.strip()
        for line in res.stdout.splitlines()
        if line.strip()
        and not line.startswith("=")
        and not line.startswith("collected")
        and not re.match(r"^\d+ tests? collected\b", line.strip())
    ]
    if not nodeids:
        sys.stderr.write("No test cases found in target path.\n")
        raise RuntimeError("no tests found")

    sys.stderr.write(f"Discovered {len(nodeids)} total tests in {elapsed:.2f}s.\n\n")
    return nodeids, elapsed


def run_single_probe(
    target_count: int,
    workers: int,
    all_nodeids: list[str],
) -> dict[str, float]:
    """
    Executes a single benchmark trial at a specific test count and worker pool.
    Returns:
        dict containing execution_seconds and total_seconds
    """
    active_subset = all_nodeids[:target_count]

    w_label = "serial (w=0)" if workers == 0 else f"-n {workers}"
    sys.stderr.write(f"  -> Probing N={target_count:<5} with {w_label:<14} ... ")
    sys.stderr.flush()

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
    if workers > 1:
        cmd.extend(["-n", str(workers)])
    cmd.extend(active_subset)

    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - t0

    if res.returncode != 0:
        sys.stderr.write(f"FAILED (code {res.returncode})\n")
        sys.stderr.write(f"{res.stdout[-800:]}\n")
        sys.stderr.write(f"{res.stderr[-800:]}\n")
        raise RuntimeError(f"Probe execution failed for N={target_count}, W={workers}")

    sys.stderr.write(f"completed in {elapsed:6.2f}s\n")
    return {"execution_seconds": elapsed, "total_seconds": elapsed}


def solve_two_point_parameters(
    w1: int, t1: float, w2: int, t2: float, gamma: float = DEFAULT_GAMMA
) -> tuple[float, float]:
    """
    Analytically solves for overhead per worker (c_w) and compute work (Work):
      T(W) = c_w * W + Work / (W ** gamma)
    """
    w1_g, w2_g = w1**gamma, w2**gamma
    w1_1g, w2_1g = w1 ** (1.0 + gamma), w2 ** (1.0 + gamma)

    denom = w2_1g - w1_1g
    if abs(denom) < 1e-6:
        return 1.0, 100.0

    c_w = (t2 * w2_g - t1 * w1_g) / denom
    c_w = max(0.01, c_w)

    work = t1 * w1_g - c_w * w1_1g
    work = max(1.0, work)

    return c_w, work


def compute_optimal_workers(
    test_count: int,
    ref_tests: int,
    work_total: float,
    c_w: float,
    n_crossover: int,
    hardware_cap: int,
    gamma: float = DEFAULT_GAMMA,
) -> int:
    """Predicts optimal worker count for any N using calibrated parameters.

    Returns 0 if test_count is below crossover threshold (serial is faster).
    Note: xdist with 1 worker is always slower than pure pytest due to overhead.
    """
    if test_count <= 0 or test_count < n_crossover:
        return 0

    scaled_work = work_total * (test_count / ref_tests)
    w_continuous = (gamma * scaled_work / c_w) ** (1.0 / (1.0 + gamma))
    rounded_w = int(round(w_continuous))

    # xdist with 1 worker adds overhead without benefit
    if rounded_w < 2:
        return 0

    return min(hardware_cap, rounded_w)


def run_calibration(
    test_args: list[str],
    cache_path: pathlib.Path | None = None,
    repo_root: pathlib.Path | None = None,
    all_nodeids: list[str] | None = None,
) -> dict[str, Any]:
    """Run 5-probe calibration and save cache."""
    phys_cores, log_cores = detect_hardware_topology()
    if all_nodeids is None:
        all_nodeids, _ = collect_test_nodeids(test_args)
    n_max = len(all_nodeids)

    n_micro = min(128, max(32, n_max // 4)) if n_max > 64 else n_max

    w_half_phys = max(2, phys_cores // 2)
    w_phys = phys_cores
    w_log = log_cores

    if w_half_phys == w_phys:
        w_half_phys = max(2, w_phys - 1)

    print("=" * 72)
    print(" FAST 5-PROBE PYTEST WORKER CALIBRATOR")
    print("=" * 72)
    print(
        f" Hardware Topology  : {phys_cores} Physical Cores | {log_cores} Logical Threads"
    )
    print(f" Total Tests (N_max): {n_max} items")
    print(f" Micro-Slice (N_min): {n_micro} items")
    print("-" * 72)

    # Phase 1: Micro-slice evaluation
    print("[Phase 1/3] Micro-slice Crossover Probes...")
    t_micro_serial = run_single_probe(n_micro, 0, all_nodeids)["total_seconds"]
    t_micro_w2 = run_single_probe(n_micro, 2, all_nodeids)["total_seconds"]

    # Phase 2: Macro-slice physical scaling
    print("\n[Phase 2/3] Macro-slice Physical Scaling Probes...")
    t_half = run_single_probe(n_max, w_half_phys, all_nodeids)["total_seconds"]
    t_phys = run_single_probe(n_max, w_phys, all_nodeids)["total_seconds"]

    # Phase 3: Hyperthreading (SMT) evaluation
    smt_beneficial = False
    t_log = t_phys
    if log_cores > phys_cores:
        print("\n[Phase 3/3] Hyperthreading (SMT) Gatekeeper Probe...")
        t_log = run_single_probe(n_max, w_log, all_nodeids)["total_seconds"]
        smt_beneficial = t_log < t_phys
    else:
        print("\n[Phase 3/3] Hyperthreading Probe: Skipped (Non-SMT CPU)")

    # Solve 2-point analytical parameters from macro probes
    c_w, work_total = solve_two_point_parameters(
        w_half_phys, t_half, w_phys, t_phys, DEFAULT_GAMMA
    )

    # Estimate crossover threshold from micro probes
    tau_serial = max(0.001, t_micro_serial / n_micro)
    spawn_delta = max(0.05, t_micro_w2 - (t_micro_serial / 2.0))
    n_crossover = max(32, int(round(spawn_delta / (tau_serial * 0.4))))

    # Determine hardware cap based on SMT trial
    if smt_beneficial:
        # Scale into hyperthreads proportionally to speedup
        speedup_factor = (t_phys - t_log) / max(0.1, t_phys)
        allowed_smt_extra = int(
            round((log_cores - phys_cores) * min(1.0, speedup_factor * 3.0))
        )
        hardware_cap = min(log_cores, phys_cores + max(1, allowed_smt_extra))
    else:
        hardware_cap = phys_cores

    unconstrained_opt = (DEFAULT_GAMMA * work_total / c_w) ** (
        1.0 / (1.0 + DEFAULT_GAMMA)
    )
    recommended_workers = min(hardware_cap, max(2, int(round(unconstrained_opt))))

    print("\n" + "=" * 72)
    print(" CALIBRATION RESULTS & DERIVED MODEL")
    print("=" * 72)
    print(f" Concurrency Scaling Exponent (gamma) : {DEFAULT_GAMMA}")
    print(f" Machine Worker Overhead (c_w)        : {c_w:.3f} s/worker")
    print(f" Parallelizable Suite Work            : {work_total:.1f} CPU-seconds")
    print(f" Serial Crossover Threshold           : N = {n_crossover} tests")
    print(
        f" SMT Hyperthreading Scaling           : {'BENEFICIAL (Enabling SMT)' if smt_beneficial else 'COUNTERPRODUCTIVE (Clamped to Physical)'}"
    )
    print(f" Effective Hardware Ceiling           : {hardware_cap} workers")
    print(
        f" Recommended Full-Suite Allocation    : -n {recommended_workers} (for N={n_max})"
    )
    print("-" * 72)

    # Predictions breakdown
    print(" Projected Worker Allocations across test counts:")
    sample_partitions = [32, 64, 128, 256, 512, 1024, 2048, 4096, n_max]
    for n in sorted(set(sample_partitions)):
        w_pred = compute_optimal_workers(
            n, n_max, work_total, c_w, n_crossover, hardware_cap, DEFAULT_GAMMA
        )
        lbl = "serial (w=0)" if w_pred == 0 else f"-n {w_pred}"
        print(f"   N = {n:<6d} -> {lbl}")
    print("=" * 72)

    # Package calibration dictionary
    results = {
        "timestamp": time.time(),
        "n_max": n_max,
        "physical_cores": phys_cores,
        "logical_cores": log_cores,
        "gamma": DEFAULT_GAMMA,
        "c_w": round(c_w, 4),
        "work_total": round(work_total, 2),
        "n_crossover": n_crossover,
        "smt_beneficial": smt_beneficial,
        "hardware_cap": hardware_cap,
        "recommended_full_suite_workers": recommended_workers,
        "raw_probes": {
            "micro_serial": round(t_micro_serial, 3),
            "micro_w2": round(t_micro_w2, 3),
            "macro_half_phys": round(t_half, 3),
            "macro_full_phys": round(t_phys, 3),
            "macro_full_log": round(t_log, 3),
        },
    }

    # Save to cache
    final_cache_path = cache_path or default_cache_path(repo_root or pathlib.Path.cwd())
    save_cache(final_cache_path, results)
    print(f"\nConfiguration saved to {final_cache_path}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Fast 5-probe pytest-xdist worker calibration optimizer."
    )
    parser.add_argument(
        "test_args",
        nargs="*",
        default=["tests"],
        help="Pytest test targets or options (default: ['tests'])",
    )
    parser.add_argument(
        "--output",
        help="Output path for calibration cache (default: shared cache location)",
    )
    args = parser.parse_args()

    repo_root = pathlib.Path.cwd()
    cache_path = pathlib.Path(args.output) if args.output else None
    run_calibration(args.test_args, cache_path=cache_path, repo_root=repo_root)


if __name__ == "__main__":
    main()
