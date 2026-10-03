"""File discovery helpers for repository scanners."""

from __future__ import annotations

from pathlib import Path


def discover_python_files() -> list[str]:
    """Return all python files in edgar_sec and tests, skipping dot-prefixed paths.

    The result is sorted so that scanner findings are reported in a stable order.
    ``Path.rglob`` yields filesystem order, which varies between machines, and a
    gate whose output reshuffles between runs cannot be diffed against itself.
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
    for root_file in ["check.py", "run.py"]:
        if (repo_root / root_file).exists():
            py_files.append(root_file)
    return sorted(py_files)
