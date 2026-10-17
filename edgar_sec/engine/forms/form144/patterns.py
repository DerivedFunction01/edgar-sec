"""Compiled regular expression patterns and vocabulary for Form 144 parsing."""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation


SEC_FILE_LABEL_RE = re.compile(
    r"(?:s\.?e\.?c\.?\s*file\s*(?:no\.?|number)?|file\s*no\.?)\s*[:\s]*([0-9]{1,3}-[0-9]{4,7})",
    re.IGNORECASE,
)
SEC_FILE_BARE_RE = re.compile(r"\b([0-9]{1,3}-[0-9]{4,7})\b")
PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
CONFORMED_SIG_RE = re.compile(r"/s/[^\S\r\n]*([A-Za-z’‘'\.\,\- ]{2,60})")
NOTICE_DATE_LABEL_RE = re.compile(
    r"(?:date of notice|date\s*:?)\s*[:\s]*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    re.IGNORECASE,
)

PLAN_ADOPTION_TERMS: tuple[str, ...] = ("plan adoption", "instruction", "rule 10b5-1")
PLAN_ADOPTION_ALT = build_alternation(PLAN_ADOPTION_TERMS)
PLAN_ADOPTION_RE = re.compile(
    rf"(?:{PLAN_ADOPTION_ALT})[^\d]{{1,50}}(\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{2,4}}|[A-Za-z]{{3,9}}\s+\d{{1,2}},?\s+\d{{4}})",
    re.IGNORECASE,
)

CLEAN_NUM_STRIP_RE = re.compile(r"[,\$]")
NUMERIC_TOKEN_RE = re.compile(r"^\s*[\$]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\b")

__all__ = [
    "CLEAN_NUM_STRIP_RE",
    "CONFORMED_SIG_RE",
    "NOTICE_DATE_LABEL_RE",
    "NUMERIC_TOKEN_RE",
    "PLAN_ADOPTION_ALT",
    "PLAN_ADOPTION_RE",
    "PLAN_ADOPTION_TERMS",
    "PHONE_RE",
    "SEC_FILE_BARE_RE",
    "SEC_FILE_LABEL_RE",
]
