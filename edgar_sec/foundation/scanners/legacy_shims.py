"""Scanner banning dead legacy behaviour and backward-compatibility shims.

An alias always looks like prudence when added, so the erosion must stay visible. Comment
noise is deliberately *not* skipped: a shim is usually announced in a comment.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

from .base import Scanner, ScannerFinding
from .lines import finding, scan_text_rule

_COMMENT_TERMS = [
    r"backwards?[- ]compatibility",
    "compatibility",
    "legacy",
    "kept for compatibility",
    "transitional shim",
    "deprecated",
]
_COMPAT_COMMENT_RE = re.compile(
    rf"#\s*{build_alternation(_COMMENT_TERMS, sort_longest_first=True)}",
    re.IGNORECASE,
)

_IDENTIFIERS = build_alternation(["legacy", "compat", "shim"])
_COMPAT_IDENTIFIER_RE = re.compile(
    rf"\b(?:def\s+_(?:{_IDENTIFIERS})\w*"
    rf"|class\s+(?:{build_alternation(['Legacy', 'Compat', 'Shim'])})\w*"
    rf"|(?:{build_alternation(['legacy_', 'compat_', 'shim_'])})\w*\s*=)",
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
    if _COMPAT_COMMENT_RE.search(line) or _COMPAT_IDENTIFIER_RE.search(line):
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
    """Flag backward-compatibility aliases, shims, and dead legacy paths.

    Comment noise is not skipped: a shim is usually announced in a comment.
    """
    return scan_text_rule(rule=_rule, skip=("check.py", "run.py"), skip_noise=False)


SCANNER = Scanner(
    name="legacy-shims",
    description="scan for backward-compatibility aliases, transitional shims, and dead legacy paths",
    run=scan_legacy_shims,
)
