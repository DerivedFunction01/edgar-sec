"""File discovery helpers for repository scanners."""

from __future__ import annotations

import subprocess
from pathlib import Path

CODE_SUFFIXES: tuple[str, ...] = (".py", ".js", ".mjs", ".ts", ".tsx", ".css", ".sh")
EXCLUDED_PARTS = frozenset({"assets", "generated"})

_ROOT_FILES = ["check.py", "run.py"]
_ROOT_CODE_FILES = ["check.py", "run.py", "init_venv.py"]


def discover_python_files() -> list[str]:
    """Return all python files in edgar_sec and tests, skipping dot-prefixed paths.

    Sorted, because ``Path.rglob`` yields filesystem order and a gate whose output
    reshuffles between runs cannot be diffed against itself.
    """
    repo_root = Path.cwd()
    py_files: list[str] = []
    scan_roots = [repo_root / "edgar_sec", repo_root / "tests"]
    for root in scan_roots:
        if root.exists():
            for p in root.rglob("*.py"):
                rel = str(p.relative_to(repo_root))
                if not any(part.startswith(".") for part in p.parts):
                    py_files.append(rel)
    for root_file in _ROOT_FILES:
        if (repo_root / root_file).exists():
            py_files.append(root_file)
    return sorted(py_files)


def tracked_paths(root: Path) -> list[str] | None:
    """Return the tracked paths under ``root`` (git ls-files), sorted.

    None when git cannot answer (not a repository, git missing): the
    caller falls back to walking the tree.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return sorted(result.stdout.splitlines())


def discover_code_files() -> list[str]:
    """Return all code files in edgar_sec and tests, per the enforcement population.

    Every ``CODE_SUFFIXES`` file under the scan roots plus the root entry
    points, skipping dot-prefixed, ``assets``, and ``generated`` paths. Sorted.
    """
    repo_root = Path.cwd()
    code_files: list[str] = []
    scan_roots = [repo_root / "edgar_sec", repo_root / "tests"]
    for root in scan_roots:
        if root.exists():
            for p in root.rglob("*"):
                if not p.is_file() or p.suffix not in CODE_SUFFIXES:
                    continue
                parts = p.relative_to(repo_root).parts
                if any(part.startswith(".") for part in parts):
                    continue
                if any(part in EXCLUDED_PARTS for part in parts):
                    continue
                code_files.append(str(p.relative_to(repo_root)))
    for root_file in _ROOT_CODE_FILES:
        if (repo_root / root_file).exists():
            code_files.append(root_file)
    return sorted(code_files)
