"""Root-level validation gate: ruff format, ruff lint, then every test suite.

Suites are run in isolation because `defs/tests` and phase tests have
`conftest.py` modules that collide when collected together. The first failing
step stops the runner with that step's exit code.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TEST_SUITES = (
    "defs/tests",
    *sorted(str(path) for path in Path("phases").glob("*/tests")),
)


def run(label: str, cmd: list[str]) -> None:
    print(f"==> {label}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="apply ruff formatting and safe lint fixes before verifying",
    )
    args = parser.parse_args()

    python = sys.executable
    ruff = [python, "-m", "ruff"]
    pytest = [python, "-m", "pytest"]

    if args.fix:
        run("ruff format (apply)", [*ruff, "format", "."])
        run("ruff check --fix (apply)", [*ruff, "check", "--fix", "."])
    run("ruff format --check", [*ruff, "format", "--check", "."])
    run("ruff check", [*ruff, "check", "."])
    for suite in TEST_SUITES:
        run(f"pytest {suite}", [*pytest, suite, "-q"])


if __name__ == "__main__":
    main()
