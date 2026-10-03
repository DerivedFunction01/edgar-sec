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
    from edgar_sec.foundation.checks.runner import run_all

    code = run_all()
    if code != 0:
        sys.exit(code)


def run_tests(
    python: str,
    explicit_paths: list[str],
    force_all: bool,
    explain: bool,
) -> None:
    if explicit_paths:
        run_cmd("explicit pytest targets", [python, "-m", "pytest", *explicit_paths])
        return

    if force_all:
        if Path("tests").is_dir() and any(Path("tests").rglob("test_*.py")):
            run_cmd("full pytest suite", [python, "-m", "pytest", "tests"])
        else:
            print("==> no tests found.")
        return

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
        run_cmd("pytest suite", [python, "-m", "pytest", "tests"])
        return

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
        for t in result.test_files:
            reasons_str = ", ".join(result.reasons.get(t, []))
            print(f"      - {t} (via {reasons_str})")

    if not result.has_tests:
        if not snapshot.has_changes:
            print(
                "==> working tree clean; no affected tests found. Use --all for full verification."
            )
        else:
            print("==> no tests affected by changes.")
        return

    print(
        f"==> running targeted pytest on {len(result.test_files)} affected test file(s)..."
    )
    run_cmd("targeted pytest", [python, "-m", "pytest", *result.test_files])


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
        run_tests(python, args.paths, args.all, args.explain)
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
    run_tests(python, args.paths, args.all, args.explain)


if __name__ == "__main__":
    main()
