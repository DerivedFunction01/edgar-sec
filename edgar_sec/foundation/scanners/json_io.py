"""Scanner routing JSON I/O through the shared serialization primitives.

A private ``canonical_json`` yields a second serialisation, so identity hashes stop agreeing;
a ``json.dump(fh)`` or ``write_text(json.dumps(...))`` can leave a truncated file. Exempt:
the modules owning those primitives.
"""

from __future__ import annotations

import re

from .base import Scanner, ScannerFinding
from .lines import finding, scan_text_rule

_REDUNDANT_DEFINITION_RE = re.compile(
    r"\bdef\s+(?:canonical_json|_canonical_json|json_canonical|_load_json)\b"
)

_NON_ATOMIC_JSON_WRITE_RE = re.compile(
    r"(?:json\.dump\s*\([^,]+,\s*(?:fh|handle|f)\b|\.write_text\(\s*json\.dumps\()"
)

# The modules that own the primitives themselves.
_ALLOWED_PREFIXES = (
    "edgar_sec/foundation/serialization.py",
    "edgar_sec/infra/storage/atomic.py",
)


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    if _REDUNDANT_DEFINITION_RE.search(line):
        return finding(
            "json-io",
            path,
            number,
            "redundant redefinition of a shared JSON helper",
            "import canonical_json from edgar_sec.foundation.serialization instead of "
            "defining a second serialisation",
        )
    if _NON_ATOMIC_JSON_WRITE_RE.search(line):
        return finding(
            "json-io",
            path,
            number,
            "ad-hoc or non-atomic JSON file write",
            "use atomic_write_json from edgar_sec.infra.storage.atomic so a crash "
            "cannot leave a truncated artifact",
        )
    return None


def scan_json_io() -> list[ScannerFinding]:
    """Flag redundant JSON helper definitions and non-atomic JSON writes."""
    return scan_text_rule(rule=_rule, prefixes=_ALLOWED_PREFIXES)


SCANNER = Scanner(
    name="json-io",
    description="scan for redundant JSON helper definitions and non-atomic JSON writes",
    run=scan_json_io,
)
