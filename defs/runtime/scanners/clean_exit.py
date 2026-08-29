"""Policy scanner enforcing clean exception raising over sys.exit in core modules."""

from __future__ import annotations

import os
import re

from defs.regex import build_alternation
from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = "exit"
_EXIT_RE = re.compile(rf"\b{build_alternation(['sys.exit', 'exit', 'os._exit'])}\s*\(")

_ALLOWED_PATHS = (
    "check.py",
    "run.py",
    "init_venv.py",
    "defs/runtime/checks.py",
    "defs/runtime/interactive.py",
    "defs/runtime/scanners/",
    "defs/runtime/settings_cli.py",
    "defs/viewer/",
    "scratch/",
)


def _is_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(
        normalized == allowed or normalized.startswith(allowed)
        for allowed in _ALLOWED_PATHS
    ):
        return True
    if normalized.endswith(("cli.py", "__main__.py")) or "/cli" in normalized:
        return True
    return is_test_file(path)


def _match_line(
    path: str, line_number: int, text: str, source: str
) -> list[ScannerFinding]:
    if _is_allowed(path):
        return []
    findings: list[ScannerFinding] = []
    if _EXIT_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="clean-exit",
                source=source,
                path=path,
                line=line_number,
                message="direct sys.exit() or exit() call in library or core phase code",
                hint="raise domain exceptions (e.g. ValueError, StorageError) instead of calling sys.exit()",
            )
        )
    return findings


def scan_clean_exit_boundary(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python files for sys.exit() calls in library/core code."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_clean_exit_boundary"]
