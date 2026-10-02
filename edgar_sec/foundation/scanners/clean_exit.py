"""Scanner banning direct sys.exit() or exit() in library code."""

from __future__ import annotations

from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_ALLOWED_ENTRYPOINTS = {"check.py", "run.py"}

_MAIN_GUARD = 'if __name__ == "__main__":'


def _is_exit_line(line: str) -> bool:
    return "sys.exit(" in line or line.strip().startswith("exit(")


def _exits_confined_to_guard(lines: list[str], guard_line: int) -> bool:
    """True when every exit call in the file sits inside the entrypoint guard.

    Exiting from ``if __name__ == "__main__":`` is how a standalone entrypoint
    signals its result. A ``sys.exit`` anywhere above the guard is still a
    library-code violation, so the whole file must be checked.
    """
    for index, line in enumerate(lines, start=1):
        if _is_exit_line(line) and index < guard_line:
            return False
    return True


def _main_guard_line(lines: list[str]) -> int | None:
    """Return the 1-based line of the module entrypoint guard, if present."""
    for index, line in enumerate(lines, start=1):
        if line.strip() == _MAIN_GUARD:
            return index
    return None


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

        lines = content.splitlines()
        guard_line = _main_guard_line(lines)
        if guard_line is not None and _exits_confined_to_guard(lines, guard_line):
            continue

        for idx, line in enumerate(lines, start=1):
            if _is_exit_line(line):
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
