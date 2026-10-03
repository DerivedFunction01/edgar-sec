"""Scanner banning hand-crafted multi-branch regex alternations.

``foundation.regex.builder`` guarantees longest-first branch ordering and safe lookaround
anchoring; both are lost once ``(?:alpha|beta|gamma)`` is written by hand. Two-branch groups
carry no ordering hazard and are deliberately not this scanner's business.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation, build_compound

from .base import Scanner, ScannerFinding
from .lines import finding, scan_text_rule

# A non-capturing group with three or more branches; two-branch groups are excluded.
_GROUP_CORE = r"""[^()|'"]+(?:\|[^()|'"]+){2,}"""
_GROUP_ALTERNATION = build_compound(
    prefix=r"\(\?:\s*",
    core=_GROUP_CORE,
    suffix=r"\s*\)",
    sep_prefix="",
    sep_suffix="",
)

# A quoted literal holding three or more pipe-separated tokens: 'a|b|c|d'
_TOKEN_ATOM = build_alternation([r"\w", r"\d", r"[a-zA-Z0-9_-]+"])
_PIPE_CHAIN_CORE = rf"(?:{_TOKEN_ATOM})(?:\|[a-zA-Z0-9_-]+){{3,}}"
_QUOTED_PIPE_CHAIN = build_compound(
    prefix=r"""['"][^'"]*?""",
    core=_PIPE_CHAIN_CORE,
    suffix=r"""[^'"]*?['"]""",
    sep_prefix="",
    sep_suffix="",
)

_RAW_ALTERNATION_RE = re.compile(
    build_alternation([_GROUP_ALTERNATION, _QUOTED_PIPE_CHAIN])
)

# The modules that own hand-written pattern vocabulary, and the DSL itself.
_ALLOWED_PREFIXES = (
    "edgar_sec/foundation/regex/",
    "edgar_sec/foundation/text/",
)

_HINT = (
    "use build_alternation or build_compound from edgar_sec.foundation.regex.builder "
    "so branches stay longest-first and lookarounds stay safely anchored"
)

_BUILDER_CALLS = ("build_alternation", "build_compound", "compact_alternation")


def _rule(path: str, number: int, line: str) -> ScannerFinding | None:
    if any(call in line for call in _BUILDER_CALLS):
        return None
    if not _RAW_ALTERNATION_RE.search(line):
        return None
    return finding(
        "regex-alternations",
        path,
        number,
        "hand-crafted multi-branch regex alternation literal",
        _HINT,
    )


def scan_regex_alternations() -> list[ScannerFinding]:
    """Flag raw 3+ branch alternation strings that should use the regex DSL."""
    return scan_text_rule(rule=_rule, prefixes=_ALLOWED_PREFIXES)


SCANNER = Scanner(
    name="regex-alternations",
    description="scan for hand-crafted 3+ branch regex alternations that bypass the builder DSL",
    run=scan_regex_alternations,
)
