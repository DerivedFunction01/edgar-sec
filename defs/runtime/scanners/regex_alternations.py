"""Policy scanner detecting raw multi-branch regex alternations that should use defs.regex."""

from __future__ import annotations

import os
import re

from defs.regex import build_alternation, build_compound
from defs.runtime.checks import ScannerFinding
from defs.runtime.scanners.engine import is_test_file, scan_patch_and_untracked

_CANDIDATE_RE = r"\|"

# 1. Non-capturing groups with 3+ branches: (?:branch1|branch2|branch3)
_GROUP_CORE = r"""[^()|'"]+(?:\|[^()|'"]+){2,}"""
_GROUP_ALTERNATION = build_compound(
    prefix=r"\(\?:\s*",
    core=_GROUP_CORE,
    suffix=r"\s*\)",
    sep_prefix="",
    sep_suffix="",
)

# 2. Quoted string literals containing 3+ pipe-separated tokens: 'a|b|c|d'
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

_ALLOWED_PATHS = (
    "defs/regex/",
    "defs/runtime/scanners/",
    "old-webpage.py",
    "old-webpage.py.txt",
    "roadmap/",
    "scratch/",
)


def _is_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if is_test_file(normalized):
        return True
    return any(normalized.startswith(prefix) for prefix in _ALLOWED_PATHS)


def _match_line(
    path: str, line_number: int, text: str, source: str
) -> list[ScannerFinding]:
    if _is_allowed(path):
        return []
    stripped = text.strip()
    if stripped.startswith(("#", "//", "/*", "*")):
        return []
    if (
        "build_alternation" in text
        or "build_compound" in text
        or "compact_alternation" in text
    ):
        return []
    if not _RAW_ALTERNATION_RE.search(text):
        return []

    return [
        ScannerFinding(
            scanner="regex-alternations",
            source=source,
            path=path,
            line=line_number,
            message="found raw multi-branch regex alternation literal",
            hint="use defs.regex.build_alternation or defs.regex.build_compound to ensure longest-first ordering and safe lookarounds",
        )
    ]


def scan_regex_alternations(
    repo_root: str | os.PathLike[str] | None = None,
) -> list[ScannerFinding]:
    """Flag raw multi-branch regex alternation strings that should use defs.regex."""
    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = ["scan_regex_alternations"]
