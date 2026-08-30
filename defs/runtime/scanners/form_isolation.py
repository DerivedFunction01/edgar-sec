"""Policy scanner ensuring generic pipeline code does not hardcode 10-K/form literals."""

from __future__ import annotations

import os
import re

from defs.regex import build_alternation
from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = "10-K|10-Q|8-K"

_FORM_PATTERNS = [r"10-K(?:/[Aa])?", r"10-Q(?:/[Aa])?", r"8-K(?:/[Aa])?"]
_FORM_LITERAL_RE = re.compile(
    rf"""(?:["']\s*{build_alternation(_FORM_PATTERNS)}\s*["']|\bform\s*==\s*["']10-)""",
    re.IGNORECASE,
)

_ALLOWED_PATHS = (
    "roadmap/",
    "defs/runtime/scanners/",
    "old-webpage.py",
    "old-webpage.py.txt",
    "scratch/",
    "phases/025_webpage_storage/processors/forms/",
    "phases/025_webpage_storage/processors/router.py",
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
    # Strip full-line comments so doc references in comments don't trip the gate
    stripped = text.strip()
    if stripped.startswith(("#", "*")):
        return []
    findings: list[ScannerFinding] = []
    if _FORM_LITERAL_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="form-isolation",
                source=source,
                path=path,
                line=line_number,
                message="hardcoded form literal (e.g. '10-K', '10-K/A') in generic pipeline code",
                hint="keep the pipeline generic across forms; pass form filters dynamically via arguments or config",
            )
        )
    return findings


def scan_form_isolation(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python files for hardcoded form literals in generic code."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        candidate_flags=re.IGNORECASE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_form_isolation"]
