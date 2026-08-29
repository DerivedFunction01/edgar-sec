"""Policy scanner enforcing the SQL AST and compiler boundary."""

from __future__ import annotations

import os
import re

from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = "SELECT|INSERT|CREATE|DROP|DELETE|UPDATE|execute"

_RAW_SQL_RE = re.compile(
    r"""(?i)(?:["']\s*(?:SELECT\s+.+\s+FROM|INSERT\s+INTO\s+|CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?TABLE\s+|DROP\s+TABLE\s+|DELETE\s+FROM\s+|UPDATE\s+\w+\s+SET)\b|\.execute\s*\(\s*["']\s*(?:SELECT|INSERT|CREATE|DROP|DELETE|UPDATE))"""
)

# Semantic areas allowed to deal with raw/driver SQL
_ALLOWED_PREFIXES = (
    "defs/sql/",
    "defs/storage/",
    "defs/viewer/",
    "phases/02_filing_extraction/core/",
    "scratch/",
)


def _is_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(normalized.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        return True
    return is_test_file(path)


def _match_line(
    path: str, line_number: int, text: str, source: str
) -> list[ScannerFinding]:
    if _is_allowed(path):
        return []
    findings: list[ScannerFinding] = []
    if _RAW_SQL_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="sql-boundary",
                source=source,
                path=path,
                line=line_number,
                message="raw SQL string literal or direct execution in phase code",
                hint="use defs.sql AST objects and compiled queries instead of raw SQL in phase code",
            )
        )
    return findings


def scan_sql_boundary(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python files for raw SQL string literals outside defs.sql/storage."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_sql_boundary"]
