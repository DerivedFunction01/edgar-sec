"""Policy scanner ensuring pipeline and phase code does not build ad-hoc path chains."""

from __future__ import annotations

import os
import re

from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

# Candidate pattern: any slash between words or chained slash operators
_CANDIDATE_RE = r"/\s*[\"']|[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+"

# 1. Chained literal path joins: e.g. path / "sub" / "leaf"
_CHAINED_LITERAL_PATH_RE = re.compile(
    r"""/\s*["'][a-zA-Z0-9_\-\.]+["']\s*/\s*["'][a-zA-Z0-9_\-\.]+["']"""
)

# 2. Deep relative path literals with 2+ path separators: e.g. "a/b/c"
_DEEP_PATH_LITERAL_RE = re.compile(
    r"""["'](?![a-zA-Z]+://)(?:[a-zA-Z0-9_\-\*]+/){2,}[a-zA-Z0-9_\-\.\*]+["']"""
)

_EXCLUSION_RE = re.compile(
    r"""(?:https?://|application/|text/|image/|%\w/%\w|FROM read_parquet)"""
)

_ALLOWED_PATHS = (
    "defs/runtime/paths.py",
    "defs/runtime/scanners/",
    "roadmap/",
    "scratch/",
)


def _is_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(
        normalized == allowed or normalized.startswith(allowed)
        for allowed in _ALLOWED_PATHS
    ):
        return True
    return is_test_file(path)


def _match_line(
    path: str, line_number: int, text: str, source: str
) -> list[ScannerFinding]:
    if _is_allowed(path):
        return []
    stripped = text.strip()
    if stripped.startswith(("#", "*", "//", "'''", '"""')):
        return []
    if _EXCLUSION_RE.search(text):
        return []

    findings: list[ScannerFinding] = []
    if _CHAINED_LITERAL_PATH_RE.search(text) or _DEEP_PATH_LITERAL_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="path-construction",
                source=source,
                path=path,
                line=line_number,
                message="ad-hoc path construction or hardcoded path-like string literal",
                hint="use defs.runtime.paths.resolve_paths() or typed layout helpers instead of literal path concatenation",
            )
        )
    return findings


def scan_path_construction(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python files for ad-hoc dataset/manifest path constructions."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_path_construction"]
