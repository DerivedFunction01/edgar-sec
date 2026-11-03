"""Signature name cleaning, validation, and delegation resolution."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.signatures import DelegationKind
from edgar_sec.engine.document.signatures import (
    CONFORMED_SIGNATURE_RE,
    RE_SIGNATURE_HTML_TAG,
)
from edgar_sec.engine.forms.common.signatures.patterns import (
    ALL_CAPS_WORD_RE,
    CLEAN_LINE_RE,
    DISALLOWED_SIGNATURE_NAME_WORDS,
    OFFICER_TITLE_RE,
    PREFIX_STRIP_RE,
    SIG_BOILERPLATE_TERMS,
    SIG_BY_PREFIX_RE,
    SIG_CONFORMED_PREFIX_RE,
    SIG_DELEGATED_NAME_RE,
    SIG_DELEGATED_SPLIT_RE,
    SIG_DELIMITER_SPLIT_RE,
    SIG_LABEL_RE,
    SIG_LEADING_RULE_RE,
    SIG_NAME_TRIM_CHARS,
    SIG_NAME_TRIM_CHARS_NO_DOT,
    SIG_SEGMENT_SPLIT_RE,
    SIG_TRAILING_PAREN_NUM_RE,
    SIG_TRAILING_PAREN_RE,
    SIGNATORY_ROLE_RE,
    TITLE_CASE_WORD_RE,
    WHITESPACE_RE,
)
from edgar_sec.foundation.text.dates import (
    MONTH_NAME_RE,
    MONTH_RE,
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
)


_NAME_INITIAL_END_RE = re.compile(r"(?:^|\s)[A-Z]\.$")

_DUPLICATE_NAME_RE = re.compile(r"^([A-Z][A-Za-z.\s',-]+?)\s+\1$")

_TRAILING_OFFICER_WORD_RE = re.compile(r"\s+officers?$", flags=re.IGNORECASE)


def is_valid_signature_name(cand: str) -> bool:
    """Validate candidate signature name string against boilerplate and length."""
    if not cand or len(cand) > 60:
        return False
    lower = cand.lower().strip(" .:-")
    if lower in {
        "date",
        "signature",
        "reporting person",
        "power of attorney",
        "attorney-in-fact",
        "attorney in fact",
        "common stock",
        "units",
        "code",
        "d",
        "i",
        "a",
        "table i",
        "table ii",
        "table 1",
        "table 2",
        "certify",
    }:
        return False
    if any(term in lower for term in SIG_BOILERPLATE_TERMS):
        return False
    if MONTH_NAME_RE.fullmatch(cand.strip(" .,")):
        return False
    if lower.rstrip(" .") in (
        "attorney-in-fact",
        "attorney in fact",
        "attorney-in-fact for",
        "attorney in fact for",
    ):
        return False
    words = cand.split()
    if not (1 <= len(words) <= 6):
        return False
    return len(words) > 1 or len(cand) >= 4


def clean_signature_name(raw_text: str) -> str:
    """Strip underline runs, prefix labels, and conformed markers from a name."""
    cleaned = RE_SIGNATURE_HTML_TAG.sub(" ", raw_text)
    cleaned = CONFORMED_SIGNATURE_RE.sub(" ", cleaned)
    cleaned = CLEAN_LINE_RE.sub(" ", cleaned)
    cleaned = SIG_BY_PREFIX_RE.sub("", cleaned.strip())
    cleaned = PREFIX_STRIP_RE.sub("", cleaned.strip())
    cleaned = SIG_TRAILING_PAREN_NUM_RE.sub("", cleaned.strip())
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    cleaned = cleaned.strip(" ,-/")
    if cleaned.endswith(".") and not _NAME_INITIAL_END_RE.search(cleaned):
        cleaned = cleaned[:-1].strip(" ,-/")
    if dup_match := _DUPLICATE_NAME_RE.match(cleaned):
        cleaned = dup_match.group(1).strip(" ,-/")
    return cleaned


def parse_conformed_signature(text: str) -> tuple[str, bool]:
    """Extract signatory name and return whether conformed markings were found."""
    is_conformed = bool(CONFORMED_SIGNATURE_RE.search(text))
    cleaned = clean_signature_name(text)
    return cleaned, is_conformed


def resolve_delegated_signer(
    text: str,
) -> tuple[str, DelegationKind, str | None]:
    """Resolve signatory name, delegation kind, and agent name if delegated."""
    cleaned = clean_signature_name(text)
    if bool(SIG_DELEGATED_NAME_RE.search(text)):
        parts = SIG_DELEGATED_SPLIT_RE.split(cleaned)
        agent = parts[0].strip(" ,.-/") if parts else None
        return cleaned, DelegationKind.POWER_OF_ATTORNEY, agent
    return cleaned, DelegationKind.DIRECT, None


def _comma_delimited(text: str, head_word: str) -> bool:
    pos = text.find(head_word)
    if pos < 0:
        return False
    return text[pos + len(head_word) :].lstrip(" \t").startswith(",")


def extract_clean_signatory_name(raw_text: str) -> str | None:
    """Extract and validate clean Title Cased signatory name from raw cell text."""
    if not raw_text:
        return None
    s = SIG_TRAILING_PAREN_RE.sub("", raw_text.strip())
    if " & " in s or " and " in s:
        segments = SIG_SEGMENT_SPLIT_RE.split(s)
        cleaned_segs = [extract_clean_signatory_name(seg) for seg in segments]
        if all(seg is not None for seg in cleaned_segs):
            return " & ".join(cleaned_segs)
        if (
            cleaned_segs
            and cleaned_segs[0] is not None
            and all(seg is None for seg in cleaned_segs[1:])
        ):
            return cleaned_segs[0]
    s = SIG_LEADING_RULE_RE.sub("", s.strip())
    s = SIG_BY_PREFIX_RE.sub("", s.strip())
    s = SIG_CONFORMED_PREFIX_RE.sub("", s.strip())
    s = SIG_LEADING_RULE_RE.sub("", s.strip())
    m_sig_label = SIG_LABEL_RE.search(s)
    if m_sig_label:
        before = s[: m_sig_label.start()].strip()
        after = s[m_sig_label.end() :].strip()
        s = before if before else after
    s = SIG_TRAILING_PAREN_NUM_RE.sub("", s.strip())
    parts = SIG_DELIMITER_SPLIT_RE.split(s)
    cand = (
        parts[0].strip(SIG_NAME_TRIM_CHARS) if parts else s.strip(SIG_NAME_TRIM_CHARS)
    )
    if len(parts) > 1 and parts[1].strip(SIG_NAME_TRIM_CHARS).lower() in (
        "jr",
        "jr.",
        "sr",
        "sr.",
        "ii",
        "iii",
        "iv",
        "v",
    ):
        cand = f"{cand}, {parts[1].strip(SIG_NAME_TRIM_CHARS_NO_DOT)}"
    elif len(parts) > 1 and len(cand.split()) == 1 and _comma_delimited(s, cand):
        rest = parts[1].strip(SIG_NAME_TRIM_CHARS_NO_DOT)
        rest_words = rest.split()
        if (
            1 <= len(rest_words) <= 3
            and all(
                TITLE_CASE_WORD_RE.match(w) or ALL_CAPS_WORD_RE.match(w)
                for w in rest_words
            )
            and not any(
                w.lower().strip(".,()'-*\u2013\u2014/")
                in DISALLOWED_SIGNATURE_NAME_WORDS
                for w in rest_words
            )
            and not OFFICER_TITLE_RE.search(rest)
            and not SIGNATORY_ROLE_RE.search(rest)
        ):
            cand = f"{cand}, {rest}"
    cand = SIG_TRAILING_PAREN_NUM_RE.sub("", cand).strip(SIG_NAME_TRIM_CHARS_NO_DOT)
    cand = NUMERIC_DATE_RE.sub("", cand).strip(SIG_NAME_TRIM_CHARS_NO_DOT)
    cand = RE_FULL_DATE.sub("", cand).strip(SIG_NAME_TRIM_CHARS_NO_DOT)
    words = cand.split()
    if not (2 <= len(words) <= 6):
        return None
    lower_words = [w.lower().strip(".,()'-*\u2013\u2014/") for w in words]
    if any(w in DISALLOWED_SIGNATURE_NAME_WORDS for w in lower_words):
        return None
    if any(MONTH_RE.fullmatch(w) for w in lower_words):
        return None
    title_probe = _TRAILING_OFFICER_WORD_RE.sub("", cand)
    if OFFICER_TITLE_RE.fullmatch(title_probe) or SIGNATORY_ROLE_RE.fullmatch(
        title_probe
    ):
        return None
    is_title_or_caps = all(
        TITLE_CASE_WORD_RE.match(w.strip(",")) or ALL_CAPS_WORD_RE.match(w.strip(","))
        for w in words
    )
    return cand if is_title_or_caps else None


__all__ = [
    "clean_signature_name",
    "extract_clean_signatory_name",
    "is_valid_signature_name",
    "parse_conformed_signature",
    "resolve_delegated_signer",
]
