"""Policy scanner ensuring pipeline and phase code do not hardcode resource allocations.

Hardcoding threads or memory limits causes out-of-memory errors in containerized
environments or throttled nodes. All components must derive resources via
``edgar_sec.foundation.runtime.resources.derive_resources()`` or accept None.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_CANDIDATE_RE = re.compile(
    r"""(?:(?:threads|max_workers)\s*(?::\s*int)?\s*=\s*[1-9]\d*|memory_limit\s*(?::\s*str)?\s*=\s*["'][0-9]+[GMK]B?["'])""",
    re.IGNORECASE,
)

_ALLOWED_PATHS = (
    "edgar_sec/foundation/runtime/resources.py",
    "edgar_sec/foundation/runtime/settings/",
    "edgar_sec/foundation/scanners/",
    "scratch/",
)


def _is_allowed(path_str: str) -> bool:
    normalized = path_str.replace("\\", "/")
    if any(
        normalized == allowed or normalized.startswith(allowed)
        for allowed in _ALLOWED_PATHS
    ):
        return True
    return (
        normalized.startswith("tests/")
        or "/tests/" in normalized
        or normalized.endswith("_test.py")
        or "/test_" in normalized
    )


def scan_resource_allocations() -> list[ScannerFinding]:
    """Scan Python files for hardcoded resource allocations (threads, memory_limit, max_workers)."""
    findings: list[ScannerFinding] = []

    for path_str in discover_python_files():
        if _is_allowed(path_str):
            continue

        path = Path(path_str)
        if not path.is_file():
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "*", '"""', "'''")):
                continue
            if _CANDIDATE_RE.search(line):
                findings.append(
                    ScannerFinding(
                        scanner="resource-allocation",
                        source="static",
                        path=path_str,
                        line=line_no,
                        message=(
                            "hardcoded resource allocation (threads, memory_limit, max_workers) "
                            "in pipeline/engine code"
                        ),
                        hint="derive resources dynamically via derive_resources() or accept None",
                    )
                )
    return findings


SCANNER = Scanner(
    name="resource-allocation",
    description="flags hardcoded thread and memory allocations to prevent OOM",
    run=scan_resource_allocations,
)

__all__ = ["SCANNER", "scan_resource_allocations"]
