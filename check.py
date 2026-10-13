"""Root validation gate: ruff format, ruff lint, policy scanners, tests.

Modes:
  python check.py              # Smart verification gate (format, lint, scanners, targeted pytest)
  python check.py --all        # Full verification gate (format, lint, scanners, full 1,942+ test suite)
  python check.py --fast       # Fast pre-commit check (format, lint, scanners; skips tests)
  python check.py --fix        # Apply formatting and safe lint fixes only (< 0.5s)
  python check.py --scan       # Run only repository policy scanners
  python check.py --test       # Run targeted pytest (or full suite with --all)
  python check.py --explain    # Diagnostic mode: explain detected changes and test lineage
  python check.py <test_path>  # Run gate with explicit test path(s) passed to pytest
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def get_calibrated_workers(
    test_count: int,
    cache_path: Path | None = None,
    recalculate: bool = False,
    calibration_nodeids: list[str] | None = None,
) -> int:
    """Get optimized worker count from calibration cache.

    Returns 0 if serial execution is optimal for the test count.
    Falls back to CPU count if calibration is missing or failed.
    """
    try:
        from edgar_sec.tools.fast_pytest_worker_calibrator import (
            compute_optimal_workers,
            load_cache,
            run_calibration,
        )
        from edgar_sec.tools.fast_pytest_worker_calibrator import default_cache_path
        from edgar_sec.foundation.runtime.resources import (
            auto_worker_count,
            available_memory_bytes,
        )

        if cache_path is None:
            repo_root = Path.cwd()
            cache_path = default_cache_path(repo_root)

        result = None if recalculate else load_cache(cache_path)
        if result is None:
            print("==> recalibrating pytest workers...")
            result = run_calibration(
                ["tests"], cache_path=cache_path, all_nodeids=calibration_nodeids
            )
        result = result.get("machine_model", result)

        c_w = result["c_w"]
        work_total = result["work_total"]
        n_crossover = result["n_crossover"]
        hardware_cap = result["hardware_cap"]
        ref_tests = result["n_max"]
        gamma = result["gamma"]

        # Calculate optimal workers for this test count
        optimal = compute_optimal_workers(
            test_count, ref_tests, work_total, c_w, n_crossover, hardware_cap, gamma
        )

        # Cap against memory-based ceiling
        mem_ceiling = auto_worker_count(available_memory_bytes())
        workers = min(optimal, mem_ceiling) if optimal > 0 else 0
        return workers if workers >= 2 else 0

    except Exception as exc:
        print(f"==> worker calibration unavailable: {exc}", file=sys.stderr)
        try:
            from edgar_sec.foundation.runtime.resources import (
                auto_worker_count,
                available_memory_bytes,
            )

            fallback = auto_worker_count(available_memory_bytes())
        except Exception:
            fallback = os.cpu_count() or 1
        return fallback if fallback >= 2 else 0


def worker_args(workers: int) -> list[str]:
    return ["-n", str(workers)] if workers >= 2 else []


def run_cmd(label: str, cmd: list[str]) -> None:
    print(f"==> {label}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def run_scanners() -> None:
    print("==> repository policy scanners")
    from edgar_sec.foundation.checks.runner import run_all

    code = run_all()
    if code != 0:
        sys.exit(code)


def run_tests(
    python: str,
    explicit_paths: list[str],
    force_all: bool,
    explain: bool,
    workers: int | None,
    recalculate: bool = False,
    calibrate: bool = False,
) -> None:
    if explicit_paths:
        test_paths = explicit_paths
        label = "explicit pytest targets"
    elif force_all:
        if Path("tests").is_dir() and any(Path("tests").rglob("test_*.py")):
            test_paths = ["tests"]
            label = "full pytest suite"
        else:
            print("==> no tests found.")
            return
    else:
        from edgar_sec.foundation.checks.git_diff import get_git_status
        from edgar_sec.foundation.checks.lineage import LineageGraph
        from edgar_sec.foundation.checks.prose import prose_only_python_files

        repo_root = Path.cwd()
        snapshot = get_git_status(repo_root)

        prose = prose_only_python_files(snapshot, repo_root)
        if prose:
            print(
                "==> prose-only python edits (comments/docstrings) excluded from selection:"
            )
            for path in sorted(prose):
                print(f"      - {path}")
            snapshot = snapshot.excluding(prose)

        if snapshot.is_docs_or_assets_only:
            print(
                "==> git change detection: only documentation, assets, or prose changed;"
                " tests skipped."
            )
            return

        if snapshot.touches_root_config:
            print("==> root configuration modified; running full pytest suite.")
            test_paths = ["tests"]
            label = "pytest suite"
        else:
            graph = LineageGraph(repo_root=repo_root)
            graph.load_cache()
            graph.sync_files()
            graph.save_cache()

            result = graph.resolve_tests(
                changed_sources=snapshot.python_sources,
                changed_tests=snapshot.python_tests,
                changed_conftests=snapshot.changed_conftests,
            )

            if explain:
                print("==> lineage & test selection explanation:")
                print(
                    f"    Modified python sources ({len(snapshot.python_sources)}): {list(snapshot.python_sources)}"
                )
                print(
                    f"    Modified python tests   ({len(snapshot.python_tests)}): {list(snapshot.python_tests)}"
                )
                print(
                    f"    Modified conftests      ({len(snapshot.changed_conftests)}): {list(snapshot.changed_conftests)}"
                )
                print(f"    Resolved test targets   ({len(result.test_files)}):")
                for test_path in result.test_files:
                    reasons_str = ", ".join(result.reasons.get(test_path, []))
                    print(f"      - {test_path} (via {reasons_str})")

            if not result.has_tests:
                if not snapshot.has_changes:
                    print(
                        "==> working tree clean; no affected tests found. Use --all for full verification."
                    )
                else:
                    print("==> no tests affected by changes.")
                return

            test_paths = list(result.test_files)
            label = "targeted pytest"
            print(
                f"==> running targeted pytest on {len(test_paths)} affected test file(s)..."
            )

    if workers is None and (calibrate or recalculate):
        from edgar_sec.tools.pytest_worker_profiles import select_workers

        try:
            target_workers = select_workers(test_paths, recalculate=recalculate)
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc) == "no tests found":
                print("==> no tests selected; skipping pytest")
                return
            print(f"==> scoped worker calibration unavailable: {exc}", file=sys.stderr)
            from edgar_sec.foundation.runtime.resources import (
                auto_worker_count,
                available_memory_bytes,
            )

            fallback = auto_worker_count(available_memory_bytes())
            target_workers = fallback if fallback >= 2 else 0
    elif workers is None:
        from edgar_sec.foundation.runtime.resources import (
            auto_worker_count,
            available_memory_bytes,
        )

        target_workers = auto_worker_count(available_memory_bytes())
    else:
        target_workers = workers

    from edgar_sec.tools.pytest_worker_profiles import record_normal_run

    with tempfile.TemporaryDirectory(prefix="pytest-worker-profile-") as tmpdir:
        profile_output = Path(tmpdir) / "profile.json"
        command = [
            python,
            "-m",
            "pytest",
            *worker_args(target_workers),
            "-p",
            "edgar_sec.tools.pytest_worker_profiles",
            "--worker-profile-output",
            str(profile_output),
            *test_paths,
        ]
        started = time.perf_counter()
        run_cmd(label, command)
        record_normal_run(
            test_paths,
            target_workers,
            time.perf_counter() - started,
            profile_output,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--fix",
        action="store_true",
        help="apply formatting and safe lint fixes and exit (< 0.5s; does not run tests)",
    )
    mode_group.add_argument(
        "--fast",
        action="store_true",
        help="quick check: format check, lint check, and scanners (skips full pytest suite)",
    )
    mode_group.add_argument(
        "--scan",
        action="store_true",
        help="run only the registered policy scanners",
    )
    mode_group.add_argument(
        "--test",
        action="store_true",
        help="run only the pytest suite (targeted by default, full with --all)",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="force execution of the full test suite across the entire repository",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="explain detected git changes and reverse dependency test lineage",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="number of pytest-xdist workers for parallel execution (default: auto-calibrate)",
    )
    parser.add_argument(
        "--recalibrate-workers",
        action="store_true",
        help="force recalibration before running tests",
    )
    parser.add_argument(
        "--calibrate-workers",
        action="store_true",
        help="run adaptive worker calibration before pytest (otherwise use the resource default)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="optional explicit test paths or files to execute via pytest",
    )

    args = parser.parse_args()
    python = sys.executable

    target_paths = ["edgar_sec", "check.py", "run.py"]
    if Path("tests").is_dir():
        target_paths.append("tests")

    # Mode 1: --fix (format & fix only, then immediately exit)
    if args.fix:
        run_cmd(
            "ruff format (applying fixes)",
            [python, "-m", "ruff", "format", *target_paths],
        )
        run_cmd(
            "ruff lint (applying safe fixes)",
            [python, "-m", "ruff", "check", "--fix", *target_paths],
        )
        print("==> fixes applied successfully.")
        return

    # Mode 2: --scan (scanners only)
    if args.scan:
        run_scanners()
        return

    # Mode 3: --test (pytest only)
    if args.test:
        run_tests(
            python,
            args.paths,
            args.all,
            args.explain,
            args.workers,
            args.recalibrate_workers,
            args.calibrate_workers,
        )
        return

    # Mode 4: Static checks (format check, lint check, policy scanners)
    run_cmd(
        "ruff format check",
        [python, "-m", "ruff", "format", "--check", *target_paths],
    )
    run_cmd("ruff lint check", [python, "-m", "ruff", "check", *target_paths])
    run_scanners()

    # If --fast, stop here without running pytest
    if args.fast:
        print("==> fast check passed (tests skipped).")
        return

    # Mode 5 (Default): Gate including targeted (or full if --all) pytest
    run_tests(
        python,
        args.paths,
        args.all,
        args.explain,
        args.workers,
        args.recalibrate_workers,
        args.calibrate_workers,
    )


if __name__ == "__main__":
    main()
