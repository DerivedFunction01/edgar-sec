"""Scanner detecting banned direct os.environ / os.getenv usage."""

from __future__ import annotations

from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_EXEMPTIONS = {
    "edgar_sec/foundation/runtime/env.py",
    "check.py",
}


def scan_environment_access() -> list[ScannerFinding]:
    """Ensure no direct os.environ calls in library code; must use get_env."""
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
            if "os.environ" in line or "os.getenv" in line:
                findings.append(
                    ScannerFinding(
                        scanner="environment-access",
                        source="static",
                        path=path_str,
                        line=idx,
                        message="Direct os.environ or os.getenv access is banned",
                        hint="Use edgar_sec.foundation.runtime.env.get_env instead.",
                    )
                )
    return findings


SCANNER = Scanner(
    name="environment-access",
    description="scan Python files for direct os.environ / os.getenv access",
    run=scan_environment_access,
)
