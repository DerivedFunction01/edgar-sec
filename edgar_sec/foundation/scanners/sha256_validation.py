"""Policy scanner banning duplicate SHA-256 string validation outside the owner."""

from __future__ import annotations

import re

from .base import Scanner, ScannerFinding
from .lines import finding, scan_text_rule

#: Regex literal that validates a full SHA-256 hex digest, e.g. ``[0-9a-f]{64}``.
_SHA256_HEX_REGEX_RE = re.compile(r"\[[0-9a-fA-F-]+\]\{64\}")

#: Lines that are SQL, not Python validation; the embedded regex is not a duplicate.
_SQL_CONTEXT_MARKERS = ("regexp_full_match", "regexp_matches")


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    if "0123456789abcdef" in line.lower():
        return finding(
            "sha256-validation",
            path,
            number,
            "private SHA-256 hex alphabet literal",
            "use edgar_sec.foundation.hashing.is_sha256_hex_digest instead of a "
            "hand-rolled length, membership, or set check",
        )
    if _SHA256_HEX_REGEX_RE.search(line) and not any(
        marker in line for marker in _SQL_CONTEXT_MARKERS
    ):
        return finding(
            "sha256-validation",
            path,
            number,
            "hand-crafted SHA-256 hex regex",
            "use edgar_sec.foundation.hashing.is_sha256_hex_digest instead of a "
            "private SHA-256 hex regex",
        )
    return None


def scan_sha256_validation() -> list[ScannerFinding]:
    """Flag Python SHA-256 string validation that duplicates the canonical helper."""
    return scan_text_rule(rule=_rule, prefixes=("edgar_sec/foundation/hashing.py",))


SCANNER = Scanner(
    name="sha256-validation",
    description="flags duplicate SHA-256 string validation outside foundation.hashing",
    run=scan_sha256_validation,
)

__all__ = ["SCANNER", "scan_sha256_validation"]
