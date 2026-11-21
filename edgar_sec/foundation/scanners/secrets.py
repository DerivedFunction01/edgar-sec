"""Scanner detecting hardcoded secrets, tokens, or credentials."""

from __future__ import annotations

import re
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_PATTERNS = [
    re.compile(
        r"""(?:api[_-]?key|secret|password|token)\s*=\s*['"][a-zA-Z0-9_\-]{16,}['"]""",
        re.IGNORECASE,
    ),
    re.compile(r"""ghp_[0-9a-zA-Z]{36}"""),
    re.compile(
        r"""sec-contact\s*:\s*['"]?[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"""
    ),
]


def scan_secrets_leakage() -> list[ScannerFinding]:
    """Scan for committed secrets or hardcoded credentials."""
    findings: list[ScannerFinding] = []
    for path_str in discover_python_files():
        if path_str.startswith("tests/") or "scanners/" in path_str:
            continue
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for idx, line in enumerate(content.splitlines(), start=1):
            for pat in _PATTERNS:
                if pat.search(line):
                    findings.append(
                        ScannerFinding(
                            scanner="secrets-leakage",
                            source="static",
                            path=path_str,
                            line=idx,
                            message="Possible hardcoded secret or email credential detected",
                            hint="Pass credentials via .env or SecSettings.",
                        )
                    )
    return findings


SCANNER = Scanner(
    name="secrets-leakage",
    description="scan Python files for committed API keys, tokens, or credentials",
    run=scan_secrets_leakage,
)
