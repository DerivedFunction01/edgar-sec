"""Policy scanner banning uncompiled module-level regex calls.

Calling ``re.search`` and friends with a pattern recompiles it on every invocation;
compile once into a module-level constant and call its method instead.
"""

from __future__ import annotations

import re
from .base import Scanner, ScannerFinding
from .lines import finding, is_noise, is_scanner_infrastructure, iter_source_lines

_UNCOMPILED_CALL_RE = re.compile(
    r"\bre\.(?:search|match|findall|finditer|split|sub|subn|fullmatch)\s*\("
)


def _scan() -> list[ScannerFinding]:
    findings: list[ScannerFinding] = []
    for path_str, number, line in iter_source_lines():
        if is_scanner_infrastructure(path_str):
            continue
        if is_noise(line):
            continue
        if _UNCOMPILED_CALL_RE.search(line):
            findings.append(
                finding(
                    "uncompiled-regex",
                    path_str,
                    number,
                    "uncompiled regex call: compile the pattern once into a module-level constant",
                    "assign re.compile(...) to a module-level constant and call its method",
                )
            )
    return findings


def scan_uncompiled_regex() -> list[ScannerFinding]:
    """Scan Python files for uncompiled regex module calls."""
    return _scan()


SCANNER = Scanner(
    name="uncompiled-regex",
    description="flags re.search/match/findall/finditer/split/sub/fullmatch calls",
    run=scan_uncompiled_regex,
)

__all__ = ["SCANNER", "scan_uncompiled_regex"]
