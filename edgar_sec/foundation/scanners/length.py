"""Scanner advising when files exceed the 800-line threshold."""

from __future__ import annotations

from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_MAX_LINES = 800


def scan_file_length() -> list[ScannerFinding]:
    """Advise when files exceed 800 lines."""
    findings: list[ScannerFinding] = []
    for path_str in discover_python_files():
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines = len(content.splitlines())
        if lines > _MAX_LINES:
            findings.append(
                ScannerFinding(
                    scanner="file-length",
                    source="static",
                    path=path_str,
                    line=lines,
                    message=f"File length is {lines} lines (exceeds recommended {_MAX_LINES} threshold)",
                    hint="Consider refactoring into smaller modular components.",
                )
            )
    return findings


SCANNER = Scanner(
    name="file-length",
    description=f"check if Python files exceed {_MAX_LINES} lines",
    run=scan_file_length,
)
