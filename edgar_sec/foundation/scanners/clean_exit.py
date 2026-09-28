"""Scanner banning direct sys.exit() or exit() in library code."""

from __future__ import annotations

from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_ALLOWED_ENTRYPOINTS = {"check.py", "run.py"}


def scan_clean_exit() -> list[ScannerFinding]:
    """Bans direct sys.exit() or exit() in engine/domain/foundation library code."""
    findings: list[ScannerFinding] = []

    for path_str in discover_python_files():
        if (
            path_str in _ALLOWED_ENTRYPOINTS
            or path_str.startswith("tests/")
            or "scanners/" in path_str
            or path_str.endswith(("cli.py", "operator.py"))
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
            if "sys.exit(" in line or line.strip().startswith("exit("):
                findings.append(
                    ScannerFinding(
                        scanner="clean-exit",
                        source="static",
                        path=path_str,
                        line=idx,
                        message="Direct sys.exit() call in library code",
                        hint="Raise a domain exception instead of calling sys.exit().",
                    )
                )
    return findings


SCANNER = Scanner(
    name="clean-exit",
    description="scan library code for direct sys.exit() calls",
    run=scan_clean_exit,
)
