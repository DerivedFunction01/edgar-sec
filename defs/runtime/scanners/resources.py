"""Policy scanner ensuring pipeline and phase code do not hardcode resource allocations."""

from __future__ import annotations

import os
import re

from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = r"threads|memory_limit|max_workers"

# Matches parameter defaults or invocations with hardcoded numeric thread counts or memory limits
_RESOURCE_LITERAL_RE = re.compile(
    r"""(?:(?:threads|max_workers)\s*(?::\s*int)?\s*=\s*[1-9]\d*|memory_limit\s*(?::\s*str)?\s*=\s*["'][0-9]+[GMK]B?["'])""",
    re.IGNORECASE,
)

_ALLOWED_PATHS = (
    "defs/runtime/resources.py",
    "defs/runtime/settings/",
    "defs/runtime/scanners/",
    "defs/storage/finalized.py",  # storage driver fallback parameters
    "defs/storage/duckdb_merge.py",  # storage driver fallback parameters
    "old-webpage.py",
    "old-webpage.py.txt",
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
    if stripped.startswith(("#", "*", '"""', "'''")):
        return []
    findings: list[ScannerFinding] = []
    if _RESOURCE_LITERAL_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="resource-allocation",
                source=source,
                path=path,
                line=line_number,
                message="hardcoded resource allocation (threads, memory_limit, max_workers) in pipeline/phase code",
                hint="derive resources dynamically via defs.runtime.resources.derive_resources() or accept None",
            )
        )
    return findings


def scan_resource_allocation(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python files for hardcoded resource numbers/limits."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        candidate_flags=re.IGNORECASE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_resource_allocation"]
