"""Policy scanner banning form-type literals under engine/tables.

Flags quoted form-type literals in edgar_sec/engine/tables/, so the
classifier layer stays form-agnostic by gate (refresh R5). Allows
exhibit-type data, stratum codes, and unquoted prose mentions.
"""

from __future__ import annotations

import re
from pathlib import Path

from edgar_sec.foundation.regex.builder import build_alternation
from .base import Scanner, ScannerFinding
from .files import discover_python_files

_FORM_PATTERNS = [
    r"10-?K(?:/[Aa])?",
    r"10-?Q(?:/[Aa])?",
    r"8-?K(?:/[Aa])?",
    r"20-?F(?:/[Aa])?",
    r"6-?K(?:/[Aa])?",
    r"S-?1(?:/[Aa])?",
    r"S-?3(?:/[Aa])?",
    r"S-?4(?:/[Aa])?",
    r"S-?8(?:/[Aa])?",
]
_FORM_LITERAL_RE = re.compile(
    rf"['\"]\s*(?:{build_alternation(_FORM_PATTERNS)})\s*['\"]",
    re.IGNORECASE,
)
_TABLES_PREFIX = "edgar_sec/engine/tables/"


def scan_tables_form_literals() -> list[ScannerFinding]:
    findings: list[ScannerFinding] = []
    for path_str in discover_python_files():
        normalized = path_str.replace("\\", "/")
        if not normalized.startswith(_TABLES_PREFIX):
            continue
        try:
            text = Path(path_str).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "*")):
                continue
            if _FORM_LITERAL_RE.search(line):
                findings.append(
                    ScannerFinding(
                        scanner="tables-form-literals",
                        source="tables_form_literals",
                        path=path_str,
                        line=line_number,
                        message="form-type literal in engine/tables code",
                        hint="form enters as detected context data; "
                        "per-form differences are profile data",
                    )
                )
    return findings


SCANNER = Scanner(
    name="tables-form-literals",
    description="ban form-type literals under engine/tables",
    run=scan_tables_form_literals,
)


__all__ = ["SCANNER", "scan_tables_form_literals"]
