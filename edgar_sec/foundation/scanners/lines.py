"""Shared line-oriented helpers for text policy scanners.

The scanners that police *source text* rather than an import graph all need the
same three things: a way to enumerate scannable lines, a way to recognise
comment/docstring noise so a rule is not reported from inside prose, and a way to
express a path allowlist. Keeping that here means a new text scanner declares its
rule and nothing else.
"""

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

    Scanners must spell out the very patterns they detect, and tests must be able
    to assert on a violation without tripping the gate themselves, so both are
    exempt from every text rule.
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

    Unreadable or non-UTF-8 files are skipped rather than failing the gate: a
    scanner that cannot decode a file has no opinion about its contents.
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

    ``rule(path, number, line)`` returns a ``ScannerFinding`` or ``None``.
    ``prefixes`` exempts the modules that legitimately own the pattern
    vocabulary; ``skip`` exempts individual files such as entrypoints.

    ``skip_noise`` drops comments and docstring delimiters before the rule runs,
    which is right for a rule about *code* but wrong for a rule about prose: a
    shim is often announced in a comment, so the legacy-shims rule turns this off
    in order to read what the author wrote.
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
