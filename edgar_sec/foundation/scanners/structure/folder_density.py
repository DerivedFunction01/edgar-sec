"""Scanner flagging folders whose direct-child code-file count passes the cap.

Over 20 direct-child code files fails the gate; the band over 16 lists as a
notice. There are no exemptions.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from ..base import SEVERITY_ERROR, SEVERITY_NOTICE, Scanner, ScannerFinding
from ..files import discover_code_files

_MAX_FILES = 20
_CREEP_FILES = 16


def folder_counts() -> dict[str, int]:
    """Count direct-child code files per folder over the enforcement population."""
    counts: dict[str, int] = {}
    for relpath in discover_code_files():
        folder = PurePosixPath(relpath).parent.as_posix()
        counts[folder] = counts.get(folder, 0) + 1
    return counts


def _finding(folder: str, severity: str, message: str) -> ScannerFinding:
    return ScannerFinding(
        scanner="folder-density",
        source="static",
        path=folder,
        line=None,
        message=message,
        severity=severity,
    )


def _folder_finding(folder: str, count: int) -> ScannerFinding | None:
    if count > _MAX_FILES:
        return _finding(
            folder,
            SEVERITY_ERROR,
            f"{count} code files exceeds the {_MAX_FILES}-file folder cap; "
            "group into subfolders by intent",
        )
    if count > _CREEP_FILES:
        return _finding(
            folder,
            SEVERITY_NOTICE,
            f"{count} code files, inside the creep band over {_CREEP_FILES}; "
            "group into subfolders by intent before the cap forces it",
        )
    return None


def scan_folder_density() -> list[ScannerFinding]:
    """Flag folders over the cap or in the creep band."""
    counts = folder_counts()
    findings: list[ScannerFinding] = []
    for folder in sorted(counts):
        finding = _folder_finding(folder, counts[folder])
        if finding is not None:
            findings.append(finding)
    return findings


SCANNER = Scanner(
    name="folder-density",
    description="enforce the per-folder code-file cap and creep band",
    run=scan_folder_density,
)
