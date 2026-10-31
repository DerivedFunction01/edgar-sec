"""Scanner banning dead legacy behaviour and backward-compatibility shims.

An alias always looks like prudence when added, so the erosion must stay visible. Comment
noise is deliberately *not* skipped: a shim is usually announced in a comment.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

from .base import Scanner, ScannerFinding
from .lines import finding, scan_text_rule

_PHRASE_TERMS = [
    r"backwards?[-_ ]compat\w*",
    r"deprecat\w*",
    r"legacy",
    r"transitional[-_ ]shim\w*",
    r"compat(?:ibility)?[-_ ]shim\w*",
    r"kept for (?:backward[-_ ])?compat\w*",
]
_COMPAT_PHRASE_RE = re.compile(
    rf"\b(?:{build_alternation(_PHRASE_TERMS, sort_longest_first=True)})\b",
    re.IGNORECASE,
)

_IDENTIFIERS = build_alternation(["legacy", "compat", "shim"])
_CLASS_NAMES = build_alternation(["Legacy", "Compat", "Shim", "Deprecated"])
_ASSIGN_PREFIXES = build_alternation(
    ["legacy_", "compat_", "shim_", "_legacy", "_compat", "_shim"]
)
_FUNC_TERMS = build_alternation(
    ["legacy", "shim", "deprecated", "backward_compat", "backwards_compat"]
)
_COMPAT_IDENTIFIERS = build_alternation(
    ["compat_", "shim_", "legacy_", "_compat_", "_shim_", "_legacy_"]
)

_COMPAT_IDENTIFIER_RE = re.compile(
    rf"\b(?:def\s+(?:\w*_)?(?:{_FUNC_TERMS})\w*"
    rf"|def\s+\w*(?:{_COMPAT_IDENTIFIERS})\w*"
    rf"|def\s+\w*(?:_compat|_shim|_legacy)\b"
    rf"|class\s+\w*(?:{_CLASS_NAMES})\w*"
    rf"|(?:{_ASSIGN_PREFIXES})\w*\s*=)",
    re.IGNORECASE,
)

# A module-level alias binding one CamelCase name to another: ``Alias = Real``.
# Both sides must be single identifiers, so ``Foo = bar.Foo`` (a re-export) and
# ``Vector = list[float]`` (a structural type alias) are out of scope.
_BARE_ALIAS_RE = re.compile(
    r"^\s*([A-Z][A-Za-z0-9_]*)\s*=\s*([A-Z][A-Za-z0-9_]*)\s*(?:#.*)?$"
)

_HINT = (
    "per AGENTS.md section 1.1 there are zero backward-compatibility shims: move the "
    "call sites instead of adding an alias, and delete the legacy path unless a "
    "documented external persistence contract requires it"
)


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    if _COMPAT_PHRASE_RE.search(line) or _COMPAT_IDENTIFIER_RE.search(line):
        return finding(
            "legacy-shims",
            path,
            number,
            "compatibility layer, legacy alias, or transitional shim",
            _HINT,
        )
    alias = _BARE_ALIAS_RE.match(line)
    if alias and alias.group(1) != alias.group(2):
        return finding(
            "legacy-shims",
            path,
            number,
            f"alias binding {alias.group(1)} to {alias.group(2)}: one public name for one class",
            _HINT + "; rename the call sites instead",
        )
    return None


def scan_legacy_shims() -> list[ScannerFinding]:
    """Flag backward-compatibility aliases, shims, and dead legacy paths."""
    return scan_text_rule(
        rule=_rule,
        skip=("check.py", "run.py"),
        skip_noise=False,
        scan_tests=True,
    )


SCANNER = Scanner(
    name="legacy-shims",
    description="scan for backward-compatibility aliases, transitional shims, and dead legacy paths",
    run=scan_legacy_shims,
)
