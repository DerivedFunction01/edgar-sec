"""Compiled regexes for legal notice filtering and header artifact detection."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.statutory import (
    HEADER_LEAK_PHRASES,
    STATUTORY_PAGE_BOILERPLATE,
)
from edgar_sec.foundation.regex.builder import build_alternation

HEADER_LEAK_ALT = build_alternation(HEADER_LEAK_PHRASES, auto_escape=True, compact=True)
HEADER_LEAK_RE = re.compile(HEADER_LEAK_ALT, re.IGNORECASE)

STATUTORY_PAGE_ARTIFACT_ALT = build_alternation(
    STATUTORY_PAGE_BOILERPLATE, auto_escape=True, compact=True
)
STATUTORY_PAGE_ARTIFACT_RE = re.compile(STATUTORY_PAGE_ARTIFACT_ALT, re.IGNORECASE)

__all__ = [
    "HEADER_LEAK_ALT",
    "HEADER_LEAK_RE",
    "STATUTORY_PAGE_ARTIFACT_ALT",
    "STATUTORY_PAGE_ARTIFACT_RE",
]
