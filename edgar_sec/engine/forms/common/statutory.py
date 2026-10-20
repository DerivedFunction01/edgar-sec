"""Compiled regexes for legal notice filtering and header artifact detection."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.statutory import (
    CERTIFICATION_DECLARATION_PHRASES,
    COMMON_FORM_PHRASE_RULES,
    HEADER_LEAK_PHRASES,
    OMB_BURDEN_PHRASES,
    RULE_10B5_1_PHRASES,
    STATUTORY_PAGE_BOILERPLATE,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.engine.forms.common.phrases import (
    PhraseMatch,
    compile_phrase_rules,
    match_phrase_rules,
)

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

_COMPILED_COMMON_FORM_PHRASE_RULES = compile_phrase_rules(COMMON_FORM_PHRASE_RULES)


def annotate_common_form_phrases(
    text: str,
    *,
    family_id: str | None = None,
    section_role: str | None = None,
    source_id: str | None = None,
) -> tuple[PhraseMatch, ...]:
    return match_phrase_rules(
        text,
        _COMPILED_COMMON_FORM_PHRASE_RULES,
        family_id=family_id,
        section_role=section_role,
        source_id=source_id,
    )


__all__ = [
    "annotate_common_form_phrases",
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
