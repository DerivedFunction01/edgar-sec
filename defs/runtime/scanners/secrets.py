"""Policy scanner detecting committed secrets, tokens, or API keys."""

from __future__ import annotations

import os
import re

from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = "sk-|ghp_|api_key|apikey|secret|password|token"

_SECRET_PATTERNS = [
    re.compile(r"""\b(?:sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,})\b"""),
    re.compile(
        r"""(?i)\b(?:api[_-]?key|secret[_-]?key|auth[_-]?token|password)\s*[:=]\s*['"]([a-zA-Z0-9_\-./+=]{16,})['"]"""
    ),
]

_SAFE_PLACEHOLDERS = (
    "placeholder",
    "test-secret",
    "dummy",
    "fake",
    "example",
    "your-api-key",
    "changeme",
)

_ALLOWED_PREFIXES = ("scratch/",)


def _is_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(normalized.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        return True
    return is_test_file(path)


def _match_line(
    path: str, line_number: int, text: str, source: str
) -> list[ScannerFinding]:
    if _is_allowed(path):
        return []
    findings: list[ScannerFinding] = []
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            captured = match.group(1) if match.groups() else match.group(0)
            if any(
                placeholder in captured.lower() for placeholder in _SAFE_PLACEHOLDERS
            ):
                continue
            findings.append(
                ScannerFinding(
                    scanner="secrets-leakage",
                    source=source,
                    path=path,
                    line=line_number,
                    message="potential committed secret or API key token in source code",
                    hint="supply credentials via environment variables (e.g. SEC_USER_AGENT) or secret manager",
                )
            )
            break
    return findings


def scan_secret_leakage(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Scan modified Python and config files for committed secrets or credentials."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        candidate_flags=re.IGNORECASE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_secret_leakage"]
