"""Compiled regexes for legal notice filtering and header artifact detection."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.statutory import (
    CERTIFICATION_DECLARATION_PHRASES,
    COMMON_FORM_PHRASE_RULES,
    FORM_FIELD_PROMPT_TERMS,
    HEADER_LEAK_PHRASES,
    OMB_BURDEN_PHRASES,
    REGULATORY_MASTHEAD_TERMS,
    RULE_10B5_1_PHRASES,
    STATUTORY_CRIMINAL_WARNING_PHRASES,
    STATUTORY_INSTRUCTION_PREFIXES,
    STATUTORY_PAGE_BOILERPLATE,
)
from edgar_sec.engine.forms.common.phrases import (
    PhraseMatch,
    compile_phrase_rules,
    match_phrase_rules,
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

INSTRUCTION_START_ALT = build_alternation(
    STATUTORY_INSTRUCTION_PREFIXES, auto_escape=True, compact=True
)
INSTRUCTION_START_RE = re.compile(rf"^\s*(?:{INSTRUCTION_START_ALT})", re.IGNORECASE)

REGULATORY_MASTHEAD_ALT = build_alternation(
    REGULATORY_MASTHEAD_TERMS, auto_escape=True, compact=True
)
REGULATORY_MASTHEAD_RE = re.compile(
    rf"\b(?:{REGULATORY_MASTHEAD_ALT})\b", re.IGNORECASE
)

STATUTORY_FIELD_PREFIX_ALT = build_alternation(
    FORM_FIELD_PROMPT_TERMS, auto_escape=True, compact=True
)
STATUTORY_FIELD_PREFIX_RE = re.compile(
    rf"^\s*(?:(?:\[?\d+[A-Za-z]?\]?\.?\s*(?:\([a-z]\))?|\(\s*[a-z]\s*\))\s*)?(?:{STATUTORY_FIELD_PREFIX_ALT})[\s:|-]*",
    re.IGNORECASE,
)

_COMPILED_COMMON_FORM_PHRASE_RULES = compile_phrase_rules(COMMON_FORM_PHRASE_RULES)


def is_pure_statutory_boilerplate(text: str) -> bool:
    """Detect whether candidate string is solely statutory instruction or header."""
    stripped = text.strip()
    if not stripped or not any(c.isalnum() for c in stripped):
        return True
    if INSTRUCTION_START_RE.search(stripped):
        return True
    if REGULATORY_MASTHEAD_RE.search(stripped):
        return True
    if STATUTORY_PAGE_ARTIFACT_RE.search(stripped):
        return True
    return False


def strip_form_prompt_prefix(text: str) -> str:
    """Strip statutory table item or prompt header prefix from candidate line."""
    return STATUTORY_FIELD_PREFIX_RE.sub("", text).strip()


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
    "CERTIFICATION_DECLARATION_ALT",
    "CERTIFICATION_DECLARATION_RE",
    "HEADER_LEAK_ALT",
    "HEADER_LEAK_RE",
    "INSTRUCTION_START_ALT",
    "INSTRUCTION_START_RE",
    "OMB_BURDEN_ALT",
    "OMB_BURDEN_RE",
    "OMB_CONTROL_RE",
    "OMB_NUMBER_RE",
    "REGULATORY_MASTHEAD_ALT",
    "REGULATORY_MASTHEAD_RE",
    "RULE_10B5_1_ALT",
    "RULE_10B5_1_RE",
    "STATUTORY_FIELD_PREFIX_ALT",
    "STATUTORY_FIELD_PREFIX_RE",
    "STATUTORY_PAGE_ARTIFACT_ALT",
    "STATUTORY_PAGE_ARTIFACT_RE",
    "annotate_common_form_phrases",
    "is_pure_statutory_boilerplate",
    "strip_form_prompt_prefix",
]
