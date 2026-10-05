"""Scanner detecting hardcoded .artifacts path literals."""

from __future__ import annotations

from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_EXEMPTIONS = {
    "edgar_sec/foundation/runtime/paths.py",
    "edgar_sec/foundation/runtime/settings/paths.py",
    "check.py",
}


def scan_artifact_paths() -> list[ScannerFinding]:
    """Ensure no hardcoded '.artifacts' path string literals."""
    findings: list[ScannerFinding] = []

    for path_str in discover_python_files():
        if (
            path_str in _EXEMPTIONS
            or path_str.startswith("tests/")
            or "scanners/" in path_str
        ):
            continue
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for idx, line in enumerate(content.splitlines(), start=1):
            if '".artifacts' in line or "'.artifacts" in line:
                findings.append(
                    ScannerFinding(
                        scanner="artifact-paths",
                        source="static",
                        path=path_str,
                        line=idx,
                        message="Hardcoded .artifacts path literal found",
                        hint="Resolve paths through edgar_sec.foundation.runtime.paths.",
                    )
                )
    return findings


SCANNER = Scanner(
    name="artifact-paths",
    description="scan Python files for hardcoded .artifacts literals",
    run=scan_artifact_paths,
)
