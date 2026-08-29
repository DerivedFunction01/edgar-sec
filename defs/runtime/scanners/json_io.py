"""Policy scanner ensuring pipeline and phase code uses shared JSON I/O primitives."""

from __future__ import annotations

import os
import re

from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = "canonical_json|json_canonical|load_json|json\\.dump|write_text"

_REDUNDANT_DEFINITION_RE = re.compile(
    r"""\bdef\s+(?:canonical_json|_canonical_json|json_canonical|_load_json)\b"""
)

_NON_ATOMIC_JSON_WRITE_RE = re.compile(
    r"""(?:json\.dump\s*\([^,]+,\s*(?:fh|handle|f)\b|\.write_text\(\s*json\.dumps\()"""
)

_ALLOWED_PATHS = (
    "defs/storage/artifacts.py",
    "defs/runtime/config_io.py",
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

    findings: list[ScannerFinding] = []
    if _REDUNDANT_DEFINITION_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="json-io",
                source=source,
                path=path,
                line=line_number,
                message="redundant definition of json helpers (e.g. canonical_json or _load_json)",
                hint="import canonical_json, load_json, or atomic_write_json from defs.storage instead",
            )
        )
    elif _NON_ATOMIC_JSON_WRITE_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="json-io",
                source=source,
                path=path,
                line=line_number,
                message="ad-hoc or non-atomic JSON file write",
                hint="use defs.storage.atomic_write_json() for crash-safe, atomic JSON writes",
            )
        )
    return findings


def scan_json_io(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python files for redundant or ad-hoc JSON I/O."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_json_io"]
