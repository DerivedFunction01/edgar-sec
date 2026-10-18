"""ASCII Form 4 layout shape classification."""

from __future__ import annotations

from enum import StrEnum
import re

from edgar_sec.foundation.regex.builder import build_alternation

_TABLE_TAG_RE = re.compile(r"<TABLE>(.*?)</TABLE>", re.IGNORECASE | re.DOTALL)
_SC_LINE_RE = re.compile(r"<\s*S\s*>", re.IGNORECASE)
_BOX_PLUS_RE = re.compile(r"\+[ \-+]{10,}\+")
_UNDERSCORE_RULE_RE = re.compile(r"^_{20,}", re.MULTILINE)
_DASH_RULE_RE = re.compile(r"^-{20,}", re.MULTILINE)
_EQ_RULE_RE = re.compile(r"^={20,}", re.MULTILINE)
_PIPE_LINE_RE = re.compile(r"^[^\n]*\|[^\n]*\|", re.MULTILINE)
_UNDERLINED_LABEL_TERMS = (
    r"name and address of reporting person\*?\s*\n\s*-{5,}",
    r"issuer name and ticker or trading symbol\s*\n\s*-{5,}",
    r"statement for month/year\s*\n\s*-{5,}",
)
_UNDERLINED_LABEL_ALT = build_alternation(_UNDERLINED_LABEL_TERMS, auto_escape=False)
_UNDERLINED_LABEL_RE = re.compile(_UNDERLINED_LABEL_ALT, re.IGNORECASE)
_STANZA_LABEL_TERMS = (
    r"1\.\s+title of security\s*:",
    r"title of security\s*:",
    r"2\.\s+transaction date\s*\(",
    r"transaction date\s*\(month/day/year\)\s*:",
)
_STANZA_LABEL_ALT = build_alternation(_STANZA_LABEL_TERMS, auto_escape=False)
_STANZA_LABEL_RE = re.compile(_STANZA_LABEL_ALT, re.IGNORECASE)
_NARRATIVE_TERMS = (
    r"information regarding joint filers and other entities",
    r"parent of nb holdings corporation",
)
_NARRATIVE_ALT = build_alternation(_NARRATIVE_TERMS, auto_escape=False)
_NARRATIVE_RE = re.compile(_NARRATIVE_ALT, re.IGNORECASE)


class AsciiShape(StrEnum):
    """Layout families for historical ASCII Form 4 filings."""

    PIPE_UNDERSCORE = "pipe_underscore"
    SC_DASH_RULES = "sc_dash_rules"
    BOX_PLUS = "box_plus"
    SC_EQ_RULES = "sc_eq_rules"
    STANZAS = "stanzas"
    SC_UNDERLINED = "sc_underlined"
    SC_ONLY = "sc_only"
    FULL_PAGE_TABLE = "full_page_table"
    NARRATIVE = "narrative"
    UNKNOWN = "unknown"


def detect_ascii_shape(text: str) -> AsciiShape:
    """Classify the structural layout family of an ASCII Form 4 filing."""
    if _NARRATIVE_RE.search(text):
        return AsciiShape.NARRATIVE

    tables = _TABLE_TAG_RE.findall(text)
    if not tables:
        if _STANZA_LABEL_RE.search(text):
            return AsciiShape.STANZAS
        return AsciiShape.UNKNOWN

    combined_tables = "\n".join(tables)

    if _BOX_PLUS_RE.search(combined_tables):
        return AsciiShape.BOX_PLUS

    if "table i" in combined_tables.lower() and _PIPE_LINE_RE.search(combined_tables):
        if "<c>" in combined_tables.lower() and "Loews Corporation" in text:
            return AsciiShape.FULL_PAGE_TABLE
        if _UNDERSCORE_RULE_RE.search(combined_tables):
            return AsciiShape.PIPE_UNDERSCORE

    has_sc = bool(_SC_LINE_RE.search(combined_tables))
    if _UNDERLINED_LABEL_RE.search(text):
        return AsciiShape.SC_UNDERLINED

    if has_sc and _EQ_RULE_RE.search(combined_tables):
        return AsciiShape.SC_EQ_RULES

    if has_sc and _DASH_RULE_RE.search(combined_tables):
        return AsciiShape.SC_DASH_RULES

    if has_sc and _UNDERSCORE_RULE_RE.search(combined_tables):
        return AsciiShape.PIPE_UNDERSCORE

    if has_sc:
        return AsciiShape.SC_ONLY

    if _STANZA_LABEL_RE.search(text):
        return AsciiShape.STANZAS

    return AsciiShape.UNKNOWN


__all__ = ["AsciiShape", "detect_ascii_shape"]
