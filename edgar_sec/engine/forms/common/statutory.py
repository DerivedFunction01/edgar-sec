"""Compiled regexes for legal notice filtering and header artifact detection."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.statutory import (
    CERTIFICATION_DECLARATION_PHRASES,
    HEADER_LEAK_PHRASES,
    OMB_BURDEN_PHRASES,
    RULE_10B5_1_PHRASES,
    STATUTORY_PAGE_BOILERPLATE,
)
from edgar_sec.foundation.regex.builder import build_alternation

HEADER_LEAK_ALT = build_alternation(HEADER_LEAK_PHRASES, auto_escape=True, compact=True)
HEADER_LEAK_RE = re.compile(HEADER_LEAK_ALT, re.IGNORECASE)

STATUTORY_PAGE_ARTIFACT_ALT = build_alternation(
    STATUTORY_PAGE_BOILERPLATE, auto_escape=True, compact=True
)
STATUTORY_PAGE_ARTIFACT_RE = re.compile(STATUTORY_PAGE_ARTIFACT_ALT, re.IGNORECASE)

OMB_CONTROL_RE = re.compile(r"(?i)\bomb\s+number\s*:?\s*(\d{4}-\d{4})\b")
OMB_NUMBER_RE = re.compile(r"\b3235-\d{4}\b")

OMB_BURDEN_ALT = build_alternation(OMB_BURDEN_PHRASES, auto_escape=True, compact=True)
OMB_BURDEN_RE = re.compile(rf"(?i)\b(?:{OMB_BURDEN_ALT})\b")

RULE_10B5_1_ALT = build_alternation(RULE_10B5_1_PHRASES, auto_escape=True, compact=True)
RULE_10B5_1_RE = re.compile(rf"(?i)\b(?:{RULE_10B5_1_ALT})\b")

CERTIFICATION_DECLARATION_ALT = build_alternation(
    CERTIFICATION_DECLARATION_PHRASES, auto_escape=True, compact=True
)
CERTIFICATION_DECLARATION_RE = re.compile(
    rf"(?i)\b(?:{CERTIFICATION_DECLARATION_ALT})\b"
)

__all__ = [
    "CERTIFICATION_DECLARATION_ALT",
    "CERTIFICATION_DECLARATION_RE",
    "HEADER_LEAK_ALT",
    "HEADER_LEAK_RE",
    "OMB_BURDEN_ALT",
    "OMB_BURDEN_RE",
    "OMB_CONTROL_RE",
    "OMB_NUMBER_RE",
    "RULE_10B5_1_ALT",
    "RULE_10B5_1_RE",
    "STATUTORY_PAGE_ARTIFACT_ALT",
    "STATUTORY_PAGE_ARTIFACT_RE",
]
