"""Root validation gate: ruff format, ruff lint, policy scanners, tests.

Modes:
  python check.py          # Full verification gate (format check, lint check, scanners, pytest)
  python check.py --fix    # Apply formatting and safe lint fixes only (< 0.5s)
  python check.py --fast   # Fast pre-commit check (format check, lint check, scanners; skips tests)
  python check.py --scan   # Run only repository policy scanners
  python check.py --test   # Run only pytest suite
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_cmd(label: str, cmd: list[str]) -> None:
    print(f"==> {label}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def run_scanners() -> None:
    print("==> repository policy scanners")
    from edgar_sec.foundation.checks import run_all

    code = run_all()
    if code != 0:
        sys.exit(code)


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
        help="run only the pytest suite",
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
        if Path("tests").is_dir() and any(Path("tests").rglob("test_*.py")):
            run_cmd("pytest suite", [python, "-m", "pytest", "tests"])
        else:
            print("==> no tests found.")
        return

    # Mode 4: Static checks (format check, lint check, policy scanners)
    run_cmd(
        "ruff format check",
        [python, "-m", "ruff", "format", "--check", *target_paths],
    )
    run_cmd("ruff lint check", [python, "-m", "ruff", "check", *target_paths])
    run_scanners()

    # If --fast, stop here without running heavy pytest suite
    if args.fast:
        print("==> fast check passed (tests skipped).")
        return

    # Mode 5 (Default): Full verification gate including pytest
    if Path("tests").is_dir() and any(Path("tests").rglob("test_*.py")):
        run_cmd("pytest suite", [python, "-m", "pytest", "tests"])


if __name__ == "__main__":
    main()
