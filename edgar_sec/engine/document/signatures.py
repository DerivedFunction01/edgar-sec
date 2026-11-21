"""Shared signature markers and lightweight signature-line detection."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.signatures import CONFORMED_SIGNATURE_TOKENS
from edgar_sec.foundation.regex.builder import build_alternation

RE_CONFORMED_SIGNATURE = re.compile(r"^\s*(?:\*\s*)?(?:By\s*:\s*|By\s+)?/\s*s\s*/\s*")

SIGNATURE_DELEGATION_TERMS: tuple[str, ...] = (
    "attorney-in-fact",
    "attorney in fact",
    "power of attorney",
    "authorized signer",
    "attorney",
    "poa",
    "esq",
)
SIGNATURE_TERMINATION_KEYWORDS: tuple[str, ...] = (
    "by:",
    "by",
    "for:",
    "date",
    "as",
    "for",
)
_DELEGATION_ALT = build_alternation(SIGNATURE_DELEGATION_TERMS, auto_escape=True)
_TERMINATION_KEYWORD_ALT = build_alternation(
    SIGNATURE_TERMINATION_KEYWORDS, auto_escape=True
)
_TERMINATION_ALT = build_alternation(
    [
        r"[,\n\r]",
        rf"\s+(?:{_TERMINATION_KEYWORD_ALT})",
        rf"\s+(?:{_DELEGATION_ALT})\b",
        r"\*{1,2}",
        r"\s*\(\d+\)",
        r"\s+[_=]{3,}",
        r"[_=]{3,}",
        r"\s+\d{1,2}[-/]",
        r"\s+\d{1,2},",
        r"\s+\d{4}",
        r"$",
    ],
    auto_escape=False,
)
_CONFORMED_PREFIX_ALT = build_alternation(
    [r"/\s*s\s*/:?", r"[sS]/\s*", r"/s\s+"], auto_escape=False
)
RE_CONFORMED_SIGNER_NAME = re.compile(
    rf"(?:By\s*:\s*|By\s+)?(?:{_CONFORMED_PREFIX_ALT})\s*([A-Za-z’‘'\.\- ]+?)(?={_TERMINATION_ALT})",
    re.IGNORECASE,
)
RE_POA_SIGNER = re.compile(r"^\s*\*\s*(?:By\s*:\s*|By\s+)", re.IGNORECASE)

SIGNATURE_LABEL_PREFIXES: tuple[str, ...] = (
    "/s/ ",
    "By:",
    "Name:",
    "Title:",
    "Date:",
    "Signature:",
)
RE_SIGNATURE_LABEL_LINE = re.compile(
    rf"^\s*(?:\*\s*)?(?:{build_alternation(SIGNATURE_LABEL_PREFIXES, auto_escape=True)})\s*",
    re.IGNORECASE,
)
RE_SIGNATURE_HEADING = re.compile(r"(?i)\bSIGNATURES?\b")
RE_SIGNATURE_DATE_LINE = re.compile(r"(?i)^\s*\(?(?:DATED|DATE)\b")
RE_SIGNATURE_ALONE = re.compile(r"(?i)^\s*signatures?\s*$")
RE_INLINE_SIGNATURE_DELIM = re.compile(r"(?i)\b(?:signature|by)\b\s*[:_]*\s*")
RE_SIGNATURE_DASHES = re.compile(r"\s*[-=_]{3,}.*$")
RE_SIGNATURE_HTML_TAG = re.compile(r"</?[^>]+>")

_SIGNATURE_TABLE_TAIL_ALT = build_alternation(
    (
        "SIGNATURE",
        "NAME",
        "NAME/TITLE",
        "TITLE",
        "DATE",
        "BY",
        "CHAIRMAN",
        r"SOLE\s+MEMBER",
        r"MANAGING\s+MEMBER",
        "MEMBER",
        "TRUSTEE",
        r"GENERAL\s+PARTNER",
        "PARTNER",
        "PRESIDENT",
        "DIRECTOR",
        "OFFICER",
        "SECRETARY",
        "TREASURER",
    ),
    auto_escape=False,
)
RE_SIGNATURE_TABLE_TAIL = re.compile(rf"(?i)\s+\(?(?:{_SIGNATURE_TABLE_TAIL_ALT})\b.*$")

_SIGNATURE_INLINE_DATE_DELIM_ALT = build_alternation(
    (r"\s+as\s+of", r"\s+[A-Z]{2,}", r"\n", r"$"),
    auto_escape=False,
)
RE_SIGNATURE_INLINE_DATE = re.compile(
    rf"(?i)\bdate\s*:\s*([0-9a-zA-Z,/\- ]{{6,20}}?)(?:{_SIGNATURE_INLINE_DATE_DELIM_ALT})"
)

_SIGNATURE_LABEL_ALT = build_alternation(
    ("signature", "name/title", "name", "title", "by:?"),
    auto_escape=False,
)
RE_SIGNATURE_LABEL = re.compile(rf"(?i)^(?:{_SIGNATURE_LABEL_ALT})$")

CONFORMED_SIGNATURE_ALT = build_alternation(
    CONFORMED_SIGNATURE_TOKENS, auto_escape=True
)
CONFORMED_SIGNATURE_RE = re.compile(rf"(?i){CONFORMED_SIGNATURE_ALT}")


def is_signature_label_line(line: str) -> bool:
    """Return whether a line opens a shared signature-block label."""
    return bool(RE_SIGNATURE_LABEL_LINE.match(line))


def is_conformed_signature_line(line: str) -> bool:
    """Return whether a raw line starts with a conformed or POA marker."""
    if "/" in line:
        return bool(RE_CONFORMED_SIGNATURE.match(line))
    return bool("*" in line and RE_POA_SIGNER.match(line))


__all__ = [
    "CONFORMED_SIGNATURE_ALT",
    "CONFORMED_SIGNATURE_RE",
    "RE_CONFORMED_SIGNATURE",
    "RE_CONFORMED_SIGNER_NAME",
    "RE_INLINE_SIGNATURE_DELIM",
    "RE_POA_SIGNER",
    "RE_SIGNATURE_ALONE",
    "RE_SIGNATURE_DASHES",
    "RE_SIGNATURE_DATE_LINE",
    "RE_SIGNATURE_HEADING",
    "RE_SIGNATURE_HTML_TAG",
    "RE_SIGNATURE_INLINE_DATE",
    "RE_SIGNATURE_LABEL",
    "RE_SIGNATURE_LABEL_LINE",
    "RE_SIGNATURE_TABLE_TAIL",
    "SIGNATURE_DELEGATION_TERMS",
    "SIGNATURE_LABEL_PREFIXES",
    "SIGNATURE_TERMINATION_KEYWORDS",
    "is_conformed_signature_line",
    "is_signature_label_line",
]
