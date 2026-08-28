"""Policy scanner enforcing the storage and persistence boundary."""

from __future__ import annotations

import os
import re

from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = r"\b(pyarrow|duckdb|sqlite3|pandas|polars)\b"

_PYARROW_IMPORT_RE = re.compile(r"^\s*(?:import\s+pyarrow|from\s+pyarrow)\b")
_DRIVER_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+(?:duckdb|sqlite3)|from\s+(?:duckdb|sqlite3)\s+import)\b"
)
_PANDAS_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+(?:pandas|polars)|from\s+(?:pandas|polars)\s+import)\b"
)

_PYARROW_ALLOWED_PREFIXES = (
    "defs/storage/",
    "defs/tests/",
    "scratch/",
)

_DRIVER_ALLOWED_PREFIXES = (
    "defs/storage/",
    "defs/sql/",
    "defs/viewer/",
    "defs/tests/",
    "scratch/",
)

_PANDAS_ALLOWED_PREFIXES = (
    "defs/tests/",
    "scratch/",
)


def _is_pyarrow_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    return any(normalized.startswith(prefix) for prefix in _PYARROW_ALLOWED_PREFIXES)


def _is_driver_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(normalized.startswith(prefix) for prefix in _DRIVER_ALLOWED_PREFIXES):
        return True
    return is_test_file(path)


def _is_pandas_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(normalized.startswith(prefix) for prefix in _PANDAS_ALLOWED_PREFIXES):
        return True
    return is_test_file(path)


def _match_line(
    path: str, line_number: int, text: str, source: str
) -> list[ScannerFinding]:
    findings: list[ScannerFinding] = []

    if _PYARROW_IMPORT_RE.search(text) and not _is_pyarrow_allowed(path):
        findings.append(
            ScannerFinding(
                scanner="storage-boundary",
                source=source,
                path=path,
                line=line_number,
                message="direct pyarrow import outside defs/storage",
                hint="import pyarrow primitives and schemas through defs.storage instead",
            )
        )

    if _DRIVER_IMPORT_RE.search(text) and not _is_driver_allowed(path):
        findings.append(
            ScannerFinding(
                scanner="storage-boundary",
                source=source,
                path=path,
                line=line_number,
                message="direct database driver import in phase code",
                hint="use defs.storage factory / executors instead of raw database drivers",
            )
        )

    if _PANDAS_IMPORT_RE.search(text) and not _is_pandas_allowed(path):
        findings.append(
            ScannerFinding(
                scanner="storage-boundary",
                source=source,
                path=path,
                line=line_number,
                message="pandas/polars import in production phase code",
                hint="use defs.storage and PyArrow schemas instead of pandas for dataset persistence",
            )
        )

    return findings


def scan_storage_boundary(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python files for persistence boundary violations."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_storage_boundary"]
