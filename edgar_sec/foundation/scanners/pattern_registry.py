"""Scanner keeping registered pattern names to their one defining home.

Flags a definition of a registered name outside its registered home;
allows uses and imports anywhere, and each name inside its own home.
Corpus tools are in scope; tests and the scanners themselves are exempt.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Scanner, ScannerFinding
from .lines import finding, is_noise, scan_text_rule

# The registry: pattern name -> the one module path allowed to define it.
PATTERN_HOMES: dict[str, str] = {
    "WORD_TOKEN_RE": "edgar_sec/foundation/text/words.py",
    "RE_FULL_DATE": "edgar_sec/foundation/text/dates.py",
    "YEAR_TOKEN_PATTERN": "edgar_sec/foundation/text/dates.py",
    "YEAR_TOKEN_RE": "edgar_sec/foundation/text/dates.py",
    "YEAR_TOKEN_SEARCH_RE": "edgar_sec/foundation/text/dates.py",
    "YEAR_IN_TEXT_RE": "edgar_sec/foundation/text/dates.py",
    "SCALE_PATTERNS": "edgar_sec/engine/tables/patterns.py",
    "UNITS_LABEL_RE": "edgar_sec/engine/tables/patterns.py",
    "normalize_text": "edgar_sec/engine/tables/extraction/normalize.py",
    "normalize_label": "edgar_sec/engine/tables/extraction/normalize.py",
    "collapse_text": "edgar_sec/engine/tables/extraction/normalize.py",
}

_DEF_RES = {name: re.compile(rf"^\s*def\s+{name}\s*\(") for name in PATTERN_HOMES}
_ASSIGN_RES = {
    name: re.compile(rf"^\s*{name}\s*(?::[^=\n]+)?=(?!=)") for name in PATTERN_HOMES
}


def _module_of(home: str) -> str:
    return home.removesuffix(".py").replace("/", ".")


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    for name, home in PATTERN_HOMES.items():
        if path == home:
            continue
        if _DEF_RES[name].search(line) or _ASSIGN_RES[name].search(line):
            return finding(
                "pattern-registry",
                path,
                number,
                f"registered pattern {name} defined outside its home",
                f"import {name} from {_module_of(home)} instead of defining a copy",
            )
    return None


def _scan_tools() -> list[ScannerFinding]:
    findings: list[ScannerFinding] = []
    tools_root = Path.cwd() / "tools"
    if not tools_root.exists():
        return findings
    paths = sorted(
        str(p.relative_to(Path.cwd()))
        for p in tools_root.rglob("*.py")
        if not any(part.startswith(".") for part in p.parts)
    )
    for path_str in paths:
        try:
            content = Path(path_str).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(content.splitlines(), start=1):
            if is_noise(line):
                continue
            found = _rule(path_str, number, line)
            if found is not None:
                findings.append(found)
    return findings


def scan_pattern_registry() -> list[ScannerFinding]:
    """Flag definitions of registered pattern names outside their home."""
    return scan_text_rule(rule=_rule) + _scan_tools()


SCANNER = Scanner(
    name="pattern-registry",
    description="scan for registered pattern names defined outside their one home",
    run=scan_pattern_registry,
)
