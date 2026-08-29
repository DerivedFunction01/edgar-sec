"""Shared patch inspection and git scanning engine for repository policy checks."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from defs.runtime.checks import ScannerFinding


def git_output(repo_root: Path | None, *args: str) -> str:
    """Execute a git command and return stripped stdout; raise on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_root) if repo_root is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def added_patch_lines(patch: str):
    """Yield ``(path, new_file_line_number, added_text)`` from a unified diff."""
    path: str | None = None
    line_number = 0
    for raw in patch.splitlines():
        if raw.startswith("+++ b/"):
            path = raw[len("+++ b/") :]
        elif raw.startswith("+++ /dev/null"):
            path = None
        elif raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            if match is not None:
                line_number = int(match.group(1))
        elif path is None:
            continue
        elif raw.startswith("+"):
            yield path, line_number, raw[1:]
            line_number += 1
        elif raw.startswith(("-", "\\")):
            continue
        else:
            line_number += 1


def is_test_file(path: str) -> bool:
    """Return True if path is a test file or in a test directory."""
    normalized = f"/{path.replace(os.sep, '/')}"
    return (
        "/tests/" in normalized
        or "/test_" in normalized
        or normalized.endswith("_test.py")
    )


def scan_patch_and_untracked(
    *,
    candidate_re: str,
    candidate_flags: int = 0,
    match_line_fn: Callable[[str, int, str, str], list[ScannerFinding]],
    repo_root: str | os.PathLike[str] | None = None,
    file_glob: str = "*.py",
) -> list[ScannerFinding]:
    """Scan staged, unstaged, and untracked changes using a matching function.

    ``match_line_fn`` receives ``(path, line_number, text, source)`` and returns findings.
    """
    root = Path(repo_root) if repo_root is not None else None
    findings: list[ScannerFinding] = []
    candidate_pattern = re.compile(candidate_re, candidate_flags)

    # Git's -G filter has no case-insensitive mode. Apply flagged candidate
    # patterns after reading the patch so scanners do not need case variants.
    use_git_candidate_filter = not candidate_flags & re.IGNORECASE

    # 1. Staged and unstaged diffs
    diff_args = (
        ("staged", ("diff", "--cached", "-U0")),
        ("unstaged", ("diff", "-U0")),
    )
    for source, base_args in diff_args:
        args = (
            (*base_args, "-G", candidate_re, "--", file_glob)
            if use_git_candidate_filter
            else (*base_args, "--", file_glob)
        )
        patch = git_output(root, *args)
        for path, line_number, text in added_patch_lines(patch):
            if not use_git_candidate_filter and not candidate_pattern.search(text):
                continue
            findings.extend(match_line_fn(path, line_number, text, source))

    # 2. Untracked files
    listing = git_output(
        root, "ls-files", "--others", "--exclude-standard", "--", file_glob
    )
    for relative in listing.splitlines():
        relative = relative.strip()
        if not relative:
            continue
        try:
            full_path = (root or Path.cwd()).joinpath(relative)
            if not full_path.is_file():
                continue
            text = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line_text in enumerate(text.splitlines(), start=1):
            findings.extend(
                match_line_fn(relative, line_number, line_text, "untracked")
            )

    findings.sort(key=lambda item: (item.source, item.path, item.line or 0))
    return findings


__all__ = [
    "added_patch_lines",
    "git_output",
    "is_test_file",
    "scan_patch_and_untracked",
]
