"""Policy scanner advising on file length and modular decomposition for modified files."""

from __future__ import annotations

import os
from pathlib import Path

from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import git_output, is_test_file

DEFAULT_MAX_LINES = 500

_ALLOWED_PATHS = (
    "scratch/",
    "init_venv.py",
    "defs/runtime/artifacts.py",
    "defs/runtime/paths.py",
    "defs/tables/templates/presentation.py",
    "phases/01_metadata_extraction/core/merge.py",
    "phases/02_filing_extraction/core/materialize.py",
)


def _is_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(
        normalized == allowed or normalized.startswith(allowed)
        for allowed in _ALLOWED_PATHS
    ):
        return True
    return is_test_file(path)


def scan_modified_file_length(
    repo_root: str | os.PathLike[str] | None = None,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
) -> list[ScannerFinding]:
    """Scan modified/untracked Python files and advise when line count exceeds max_lines."""
    root = Path(repo_root) if repo_root is not None else None
    findings: list[ScannerFinding] = []
    seen: set[str] = set()

    # Staged, unstaged, and untracked files
    for source, args in (
        (
            "staged",
            ("diff", "--cached", "--name-only", "--diff-filter=d", "--", "*.py"),
        ),
        ("unstaged", ("diff", "--name-only", "--diff-filter=d", "--", "*.py")),
        ("untracked", ("ls-files", "--others", "--exclude-standard", "--", "*.py")),
    ):
        output = git_output(root, *args)
        for relative in output.splitlines():
            relative = relative.strip()
            if not relative or relative in seen or _is_allowed(relative):
                continue
            seen.add(relative)

            full_path = (root or Path.cwd()).joinpath(relative)
            if not full_path.is_file():
                continue
            try:
                line_count = len(full_path.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeDecodeError):
                continue

            if line_count > max_lines:
                findings.append(
                    ScannerFinding(
                        scanner="file-length",
                        source=source,
                        path=relative,
                        line=None,
                        message=f"file length is {line_count} lines (exceeds {max_lines} lines threshold)",
                        hint="consider splitting this module into focused submodules (e.g. data schemas, parsing helpers, execution logic)",
                    )
                )

    findings.sort(key=lambda item: (item.source, item.path))
    return findings


__all__ = ["DEFAULT_MAX_LINES", "scan_modified_file_length"]
