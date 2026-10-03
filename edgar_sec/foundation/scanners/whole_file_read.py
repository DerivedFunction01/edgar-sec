"""Policy scanner banning whole-file reads that feed a hash.

Materializing an artifact to digest it exhausts memory on a large one, so ``file_sha256``
streams instead. Narrow on purpose: only a ``read_bytes()`` a digest constructor consumes.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

# Digest constructors. The pattern needs ``(`` immediately after, so ``sha256_text``
# and friends never match.
_HASH_TOKENS = (
    r"(?:hashlib\.)?"
    r"(?:sha1|sha224|sha256|sha384|sha512|sha3_\d+|shake_\d+|md5|blake2[bs])"
)

# A digest whose argument reaches ``.read_bytes()`` on the same line, so a hash three
# statements away cannot borrow the read.
_HASHING_READ = re.compile(rf"{_HASH_TOKENS}\s*\([^\n]{{0,200}}?\.read_bytes\(\)")

_ALLOWED_PATHS = (
    "edgar_sec/foundation/scanners/",
    "edgar_sec/foundation/hashing.py",
)


def _is_allowed(path_str: str) -> bool:
    normalized = path_str.replace("\\", "/")
    if any(normalized.startswith(allowed) for allowed in _ALLOWED_PATHS):
        return True
    return (
        normalized.startswith("tests/")
        or "/tests/" in normalized
        or "/test_" in normalized
        or normalized.endswith("_test.py")
    )


def scan_whole_file_reads() -> list[ScannerFinding]:
    """Scan Python files for whole-file reads consumed by a digest."""
    findings: list[ScannerFinding] = []

    for path_str in discover_python_files():
        if _is_allowed(path_str):
            continue

        path = Path(path_str)
        if not path.is_file():
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "*", '"""', "'''")):
                continue
            if _HASHING_READ.search(line):
                findings.append(
                    ScannerFinding(
                        scanner="whole-file-read",
                        source="static",
                        path=path_str,
                        line=line_no,
                        message="whole-file read consumed by a digest constructor",
                        hint=(
                            "use foundation.hashing.file_sha256 to stream the file "
                            "in blocks instead of materializing it"
                        ),
                    )
                )
    return findings


SCANNER = Scanner(
    name="whole-file-read",
    description="flags read_bytes() feeding a hash, which buffers whole artifacts",
    run=scan_whole_file_reads,
)

__all__ = ["SCANNER", "scan_whole_file_reads"]
