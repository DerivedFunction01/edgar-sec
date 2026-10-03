"""Shared line-oriented helpers for text policy scanners."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from .base import ScannerFinding
from .files import discover_python_files

# A line whose first non-space characters are one of these is prose, not code.
_COMMENT_PREFIXES = ("#", "//", "/*", "*", '"""', "'''")

Rule = Callable[[str, int, str], ScannerFinding | None]


def is_noise(line: str) -> bool:
    """True when the line is a comment or a docstring delimiter."""
    return line.strip().startswith(_COMMENT_PREFIXES)


def is_scanner_infrastructure(path: str) -> bool:
    """True for the scanners themselves and for test files.

    Both must spell out the patterns they detect, or assert on a violation.
    """
    return "foundation/scanners/" in path or path.startswith("tests/")


def matches_allowed(path: str, prefixes: Sequence[str]) -> bool:
    """True when ``path`` is the allowlisted module itself or lives under it."""
    normalised = path.replace("\\", "/")
    return any(
        normalised == prefix.rstrip("/") or normalised.startswith(prefix)
        for prefix in prefixes
    )


def iter_source_lines() -> Iterator[tuple[str, int, str]]:
    """Yield ``(path, line_number, line)`` for every readable Python line.

    An undecodable file is skipped, not fatal: the scanner has no opinion on it.
    """
    for path_str in discover_python_files():
        try:
            content = Path(path_str).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            yield path_str, number, line


def scan_text_rule(
    rule: Rule,
    prefixes: Sequence[str] = (),
    skip: Sequence[str] = (),
    skip_noise: bool = True,
) -> list[ScannerFinding]:
    """Apply a per-line rule across the tree and return the findings.

    ``prefixes`` exempts modules owning the pattern vocabulary; ``skip`` exempts files.
    ``skip_noise`` suits a code rule, not a prose one, so the legacy-shims rule turns it off.
    """
    findings = []
    for path_str, number, line in iter_source_lines():
        if is_scanner_infrastructure(path_str) or path_str in skip:
            continue
        if matches_allowed(path_str, prefixes):
            continue
        if skip_noise and is_noise(line):
            continue
        found = rule(path_str, number, line)
        if found is not None:
            findings.append(found)
    return findings


def finding(
    scanner: str, path: str, number: int, message: str, hint: str
) -> ScannerFinding:
    """Build a ``ScannerFinding`` with this package's conventional source tag."""
    return ScannerFinding(
        scanner=scanner,
        source="static",
        path=path,
        line=number,
        message=message,
        hint=hint,
    )
