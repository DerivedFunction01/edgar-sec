"""Policy scanner detecting dead legacy behavior, backward-compatibility aliases, and shims."""

from __future__ import annotations

import os
import re

from defs.regex import build_alternation
from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = "legacy|compat|backward|deprecated|shim"

_COMMENT_TERMS = [
    r"backwards?[- ]compatibility",
    "compatibility",
    "legacy",
    "kept for compatibility",
    "transitional shim",
    "deprecated",
]
_COMPAT_COMMENT_RE = re.compile(
    rf"(?i)#\s*{build_alternation(_COMMENT_TERMS, sort_longest_first=True)}",
    re.IGNORECASE,
)
_IDENTIFIERS = ["legacy", "compat", "shim"]
_COMPAT_IDENTIFIER_RE = re.compile(
    rf"(?i)\b(?:def\s+_(?:{build_alternation(_IDENTIFIERS)})\w*|class\s+(?:{build_alternation(['Legacy', 'Compat', 'Shim'])})\w*|(?:{build_alternation(['legacy_', 'compat_', 'shim_'])})\w*\s*=)",
    re.IGNORECASE,
)

# Semantic areas with documented external contracts (e.g. cross-machine unmanifested artifact bootstrap)
_ALLOWED_PATHS = (
    "defs/runtime/artifacts.py",
    "defs/runtime/scanners/",
    "scratch/",
    "check.py",
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
    findings: list[ScannerFinding] = []
    if _COMPAT_COMMENT_RE.search(text) or _COMPAT_IDENTIFIER_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="legacy-shims",
                source=source,
                path=path,
                line=line_number,
                message="compatibility layer, legacy alias, or transitional shim detected",
                hint=(
                    "Per AGENTS.md, do not retain dead legacy behavior or shims when the only consumers "
                    "are internal/tests or part of a breaking refactor; eliminate the legacy path unless "
                    "backed by a documented external persistence contract."
                ),
            )
        )
    return findings


def scan_legacy_shims(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python files for backward compatibility aliases and legacy shims."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        candidate_flags=re.IGNORECASE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_legacy_shims"]
