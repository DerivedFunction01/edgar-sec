"""Policy scanner ensuring generic pipeline code does not hardcode form literals.

Form-specific code must be confined to edgar_sec/domain/forms/ and tests/domain/forms/.
"""

from __future__ import annotations

import os
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
]
_FORM_LITERAL_RE = re.compile(
    rf"(?:['\"]\s*({build_alternation(_FORM_PATTERNS)})\s*['\"]|\bform\s*==\s*['\"](?:10-|20-|8-|6-|S-))",
    re.IGNORECASE,
)

_ALLOWED_PATHS = (
    "edgar_sec/domain/forms/families/annual/",
    "edgar_sec/domain/forms/families/quarterly/",
    "edgar_sec/domain/forms/families/current/",
    "edgar_sec/domain/forms/families/registration/",
    "edgar_sec/engine/forms/registration/",
    "tests/",
    "edgar_sec/domain/forms/common/aliases.py",
    "edgar_sec/engine/forms/plugins/registry.py",
    "edgar_sec/engine/forms/cover/profiles.py",
    "edgar_sec/foundation/scanners/form_isolation.py",
    "edgar_sec/domain/forms/exhibits/profiles.py",
    "edgar_sec/domain/forms/families/processing_profiles.py",
    "edgar_sec/pipelines/document_inventory/progress_scale_check.py",
)


def _is_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(
        normalized == allowed or normalized.startswith(allowed)
        for allowed in _ALLOWED_PATHS
    ):
        return True
    return False


def scan_form_isolation() -> list[ScannerFinding]:
    findings: list[ScannerFinding] = []
    for path_str in discover_python_files():
        if not _is_allowed(path_str):
            try:
                text = Path(path_str).read_text(encoding="utf-8")
                for line_number, line in enumerate(text.splitlines(), start=1):
                    stripped = line.strip()
                    if stripped.startswith(("#", "*")):
                        continue
                    if _FORM_LITERAL_RE.search(line):
                        findings.append(
                            ScannerFinding(
                                scanner="form-isolation",
                                source="form_isolation",
                                path=path_str,
                                line=line_number,
                                message="hardcoded form literal (e.g. '10-K', '10-K/A') in generic code",
                                hint="keep all code form agnostic; pass form filters via arguments or config",
                            )
                        )
            except (OSError, UnicodeDecodeError):
                continue
    return findings


SCANNER = Scanner(
    name="form-isolation",
    description="prevent hardcoded form literals in generic code",
    run=scan_form_isolation,
)


__all__ = ["SCANNER", "scan_form_isolation"]
