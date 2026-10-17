"""Reusable parsing utilities for conformed signature blocks and delegations."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.signatures import (
    COMMON_SIGNATURE_LEXICAL_PACK,
    CONFORMED_SIGNATURE_TOKENS,
    CORPORATE_OFFICER_TITLES,
    CORPORATE_SIGNATORY_ROLES,
    NOTARY_AND_JURAT_PHRASES,
    POA_AUTH_TERMS,
    DelegationKind,
    Signatory,
    SignatureBlock,
)
from edgar_sec.engine.document.page_markers.signatures import (
    RE_CONFORMED_SIGNER_NAME,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.automaton import tokenize
from edgar_sec.foundation.text.dates import (
    MONTH_RE,
    NUMERIC_DATE_RE,
    RE_FULL_DATE,
)
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)

CONFORMED_SIGNATURE_ALT = build_alternation(
    CONFORMED_SIGNATURE_TOKENS, auto_escape=True
)
CONFORMED_SIGNATURE_RE = re.compile(rf"(?i){CONFORMED_SIGNATURE_ALT}")
CLEAN_LINE_RE = re.compile(r"[_=\-\*]{2,}")
WHITESPACE_RE = re.compile(r"\s+")
PREFIX_STRIP_TERMS = (
    r"by\s*:?",
    r"for\s*:?",
    r"signature\s*:?",
)
PREFIX_STRIP_ALT = build_alternation(PREFIX_STRIP_TERMS, auto_escape=False)
PREFIX_STRIP_RE = re.compile(rf"(?i)^(?:{PREFIX_STRIP_ALT})\s*")

NOTARY_JURAT_ALT = build_alternation(
    NOTARY_AND_JURAT_PHRASES, auto_escape=True, compact=True
)
NOTARY_JURAT_RE = re.compile(NOTARY_JURAT_ALT, re.IGNORECASE)

OFFICER_TITLE_ALT = build_alternation(
    CORPORATE_OFFICER_TITLES, auto_escape=True, compact=True
)
OFFICER_TITLE_RE = re.compile(OFFICER_TITLE_ALT, re.IGNORECASE)

SIGNATORY_ROLE_ALT = build_alternation(
    CORPORATE_SIGNATORY_ROLES, auto_escape=True, compact=True
)
SIGNATORY_ROLE_RE = re.compile(SIGNATORY_ROLE_ALT, re.IGNORECASE)

POA_AUTH_ALT = build_alternation(POA_AUTH_TERMS, auto_escape=True, compact=True)
POA_AUTH_RE = re.compile(POA_AUTH_ALT, re.IGNORECASE)

SIG_NAME_TERMINATOR_ALT = build_alternation(
    [r"\s+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", r"\n", r"$"],
    auto_escape=False,
)
SIG_NAME_RE = re.compile(
    rf"Signature of Reporting Person(?:\s+Date)?\s+([A-Za-z’‘'\.\- ]+?)(?:{SIG_NAME_TERMINATOR_ALT})",
    re.IGNORECASE,
)
SIG_BY_NAME_TITLE_ALT = build_alternation(
    (
        "dir",
        "director",
        "officer",
        "president",
        "pres",
        "treasurer",
        "treas",
        "secretary",
        "sec",
        "chief",
        "exec",
        "executive",
        "vice",
        "principal",
        "accounting",
        "financial",
        "attorney",
        "comp",
        "prog",
    ),
    auto_escape=True,
)
SIG_BY_NAME_TERMINATOR_ALT = build_alternation(
    [
        r"\n",
        r"For\s*:",
        r"Date\b",
        r"\(?\s*POA\b",
        r",?\s+attorney-in-fact\b",
        r"\s*-\s*attorney-in-fact\b",
        r",?\s+attorney\s+in\s+fact\b",
        r",?\s+power\s+of\s+attorney\b",
        r",?\s+authorized\s+signer\b",
        r",?\s+attorney\b",
        r",?\s+poa\b",
        r",?\s+esq\b",
        rf",?\s+(?:{SIG_BY_NAME_TITLE_ALT})\b\.?",
        r"$",
    ],
    auto_escape=False,
)
SIG_BY_NAME_RE = re.compile(
    r"\bBy\s*:\s*(?:By\s+)?(?:/\s*s\s*/\s*)?"
    r"([A-Za-z][A-Za-z.,’‘\-']*(?:\s+[A-Za-z][A-Za-z.,’‘\-']*){0,5}?)"
    rf"(?=\s*(?:{SIG_BY_NAME_TERMINATOR_ALT}))",
    re.IGNORECASE,
)
SIG_DELEGATED_NAME_SUFFIX_ALT = build_alternation(
    ("power of attorney", "attorney-in-fact", "attorney in fact"),
    auto_escape=True,
)
SIG_DELEGATED_NAME_RE = re.compile(
    r"(?:^|\n)\s*([A-Za-z][A-Za-z.,’‘\-']*(?:\s+[A-Za-z][A-Za-z.,’‘\-']*){1,5}?)"
    rf"\s*,?\s+(?:{SIG_DELEGATED_NAME_SUFFIX_ALT})\b",
    re.IGNORECASE,
)
SIG_UNDERLINED_NAME_RE = re.compile(
    r"[_=-]{2,}\s*"
    r"([A-Za-z][A-Za-z.,’‘\-']*(?:\s+[A-Za-z][A-Za-z.,’‘\-']*){1,5}?)"
    r"\s*[_=-]{2,}",
    re.IGNORECASE,
)
SIG_PERSON_PREFIX_RE = re.compile(
    r"(?:^|\n)[^\S\r\n]*([A-Za-z’‘'\.\- ]{3,40}?)[^\S\r\n]*\n(?:\s*\d{2,4}\s*\n)?\s*\*{1,2}\s*Signature of Reporting Person",
    re.IGNORECASE,
)
SIG_BOILERPLATE_TERMS: tuple[str, ...] = (
    "criminal",
    "violation",
    "omb",
    "federal",
    "intentional",
    "misstatement",
    "instruction",
    "valid omb",
    "respond",
    "warning",
    "pursuant",
    "reminder",
    "note:",
    "potential persons",
    "displays a currently",
    "18 u.s.c.",
    "15 u.s.c.",
    "sec 1474",
    "sec 2474",
)

SIGNATURE_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    RE_CONFORMED_SIGNER_NAME,
    SIG_UNDERLINED_NAME_RE,
    SIG_BY_NAME_RE,
    SIG_DELEGATED_NAME_RE,
    SIG_PERSON_PREFIX_RE,
    SIG_NAME_RE,
)


def is_valid_signature_name(cand: str) -> bool:
    """Validate candidate signature name string against boilerplate and length."""
    if not cand or len(cand) > 60:
        return False
    lower = cand.lower()
    if lower.strip(" .:-") in {
        "date",
        "signature",
        "power of attorney",
        "attorney-in-fact",
        "attorney in fact",
    }:
        return False
    if any(term in lower for term in SIG_BOILERPLATE_TERMS):
        return False
    words = cand.split()
    return 1 <= len(words) <= 6


def clean_signature_name(raw_text: str) -> str:
    """Strip underline runs, prefix labels, and conformed markers from a name."""
    cleaned = CONFORMED_SIGNATURE_RE.sub(" ", raw_text)
    cleaned = CLEAN_LINE_RE.sub(" ", cleaned)
    cleaned = PREFIX_STRIP_RE.sub("", cleaned.strip())
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned.strip(" ,.-/")


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
        parts = re.split(rf"(?i)\b(?:{SIG_DELEGATED_NAME_SUFFIX_ALT})\b", cleaned)
        agent = parts[0].strip(" ,.-/") if parts else None
        return cleaned, DelegationKind.POWER_OF_ATTORNEY, agent
    return cleaned, DelegationKind.DIRECT, None


def extract_signature_candidate(sig_text: str) -> tuple[str | None, str | None]:
    """Extract signature name and signature date from cleaned signature block text."""
    sig_name: str | None = None
    sig_date: str | None = None
    m_date = RE_FULL_DATE.search(sig_text) or NUMERIC_DATE_RE.search(sig_text)
    if m_date:
        sig_date = m_date.group(0).strip()
    lower = sig_text.lower()
    has_sig_rep_person = "signature of reporting person" in lower
    for pattern in SIGNATURE_NAME_PATTERNS:
        if (
            pattern is SIG_PERSON_PREFIX_RE or pattern is SIG_NAME_RE
        ) and not has_sig_rep_person:
            continue
        match = pattern.search(sig_text)
        if match:
            candidate = match.group(1).strip(" ,.-")
            if is_valid_signature_name(candidate):
                sig_name = candidate
                break
    return sig_name, sig_date


def extract_signature_block(text: str) -> SignatureBlock | None:
    """Parse text into a structured signature block with detected signatories."""
    if not text.strip():
        return None
    has_notary = bool(NOTARY_JURAT_RE.search(text))
    sig_name, sig_date = extract_signature_candidate(text)
    signatories: list[Signatory] = []
    if sig_name:
        signatories.append(Signatory(name=sig_name, date=sig_date))
    return SignatureBlock(
        signatories=tuple(signatories),
        is_conformed=bool(CONFORMED_SIGNATURE_RE.search(text)),
        has_notary=has_notary,
        raw_text=text,
    )


_COMPILED_SIGNATURE_PACK = compile_evidence_pack(COMMON_SIGNATURE_LEXICAL_PACK)
_EVIDENCE_CTX = EvidenceContext(min_words=1)


def is_signature_table(
    lower: str,
    past_tables: bool,
    *,
    extra_markers: tuple[str, ...] = (),
) -> bool:
    """Classify whether table text represents a conformed signature section."""
    if not past_tables and not any(
        k in lower
        for k in (
            "signature",
            "misstatement",
            "criminal",
            "presents",
            "attorney",
            "notary",
            "sworn",
            "signatory",
            "yours",
        )
    ):
        return False
    score = score_tokens(tokenize(lower), _COMPILED_SIGNATURE_PACK, _EVIDENCE_CTX)
    if "signature_decisive" in score.satisfied_tiers and not score.exclusions:
        return True
    if not past_tables:
        return False
    if any(marker in lower for marker in ("/s/", "-s-", "signature:", *extra_markers)):
        return True
    if (
        len(lower) < 80
        and ("date" in lower or "dated" in lower)
        and bool(NUMERIC_DATE_RE.search(lower) or MONTH_RE.search(lower))
    ):
        return True
    return score.score >= 2 and not score.exclusions


__all__ = [
    "CLEAN_LINE_RE",
    "CONFORMED_SIGNATURE_ALT",
    "CONFORMED_SIGNATURE_RE",
    "NOTARY_JURAT_ALT",
    "NOTARY_JURAT_RE",
    "OFFICER_TITLE_ALT",
    "OFFICER_TITLE_RE",
    "POA_AUTH_ALT",
    "POA_AUTH_RE",
    "PREFIX_STRIP_ALT",
    "PREFIX_STRIP_RE",
    "PREFIX_STRIP_TERMS",
    "SIGNATORY_ROLE_ALT",
    "SIGNATORY_ROLE_RE",
    "SIGNATURE_NAME_PATTERNS",
    "SIG_BOILERPLATE_TERMS",
    "SIG_BY_NAME_RE",
    "SIG_BY_NAME_TERMINATOR_ALT",
    "SIG_BY_NAME_TITLE_ALT",
    "SIG_DELEGATED_NAME_RE",
    "SIG_DELEGATED_NAME_SUFFIX_ALT",
    "SIG_NAME_RE",
    "SIG_NAME_TERMINATOR_ALT",
    "SIG_PERSON_PREFIX_RE",
    "SIG_UNDERLINED_NAME_RE",
    "WHITESPACE_RE",
    "clean_signature_name",
    "extract_signature_block",
    "extract_signature_candidate",
    "is_signature_table",
    "is_valid_signature_name",
    "parse_conformed_signature",
    "resolve_delegated_signer",
]
