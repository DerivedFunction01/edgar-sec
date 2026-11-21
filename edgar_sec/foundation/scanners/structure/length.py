"""Scanner enforcing the 800-line cap and the 700-line creep band.

The cap fails the gate; the band lists as a notice (suites are
band-exempt). There are no exemptions.
"""

from __future__ import annotations

from pathlib import Path

from ..base import SEVERITY_ERROR, SEVERITY_NOTICE, Scanner, ScannerFinding
from ..files import discover_code_files

_MAX_LINES = 800
_CREEP_LINES = 700


def _is_suite(relpath: str) -> bool:
    name = Path(relpath).name
    return (
        name.startswith("test_")
        or Path(name).stem.endswith("_test")
        or ".test." in name
        or ".spec." in name
    )


def _finding(
    relpath: str,
    line: int | None,
    message: str,
    hint: str = "",
    severity: str = SEVERITY_ERROR,
) -> ScannerFinding:
    return ScannerFinding(
        scanner="file-length",
        source="static",
        path=relpath,
        line=line,
        message=message,
        hint=hint,
        severity=severity,
    )


def _creep_notice(relpath: str, count: int) -> ScannerFinding:
    return _finding(
        relpath,
        count,
        f"File length is {count} lines (creep band {_CREEP_LINES}-{_MAX_LINES}); "
        "decompose before the cap forces it",
        severity=SEVERITY_NOTICE,
    )


def scan_file_length() -> list[ScannerFinding]:
    """Flag files over the cap and notice files in the creep band."""
    findings: list[ScannerFinding] = []
    for relpath in discover_code_files():
        try:
            count = len(Path(relpath).read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            continue
        if count > _MAX_LINES:
            findings.append(
                _finding(
                    relpath,
                    count,
                    f"File length is {count} lines (exceeds the {_MAX_LINES}-line cap)",
                    hint="Consider refactoring into smaller modular components.",
                )
            )
        elif count >= _CREEP_LINES and not _is_suite(relpath):
            findings.append(_creep_notice(relpath, count))
    return findings


SCANNER = Scanner(
    name="file-length",
    description=(
        f"enforce the {_MAX_LINES}-line cap and the {_CREEP_LINES}-line creep band"
    ),
    run=scan_file_length,
)
