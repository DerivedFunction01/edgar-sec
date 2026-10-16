"""Compiled regexes and parsers for reporting persons, issuers, and addresses."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.entities import (
    EXCHANGE_PREFIX_TERMS,
    ISSUER_LABEL_TERMS,
    NON_OWNER_JURISDICTION_TERMS,
    STREET_ANCHOR_TERMS,
    SYMBOL_TERMS,
    TEMPLATE_LABELS,
)
from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES
from edgar_sec.foundation.regex.builder import build_alternation

STATE_ALT = build_alternation(sorted(STATE_POSTAL_CODES))
STATE_ZIP_RE = re.compile(rf"\b({STATE_ALT})\s+(\d{{5}}(?:-\d{{4}})?)\b")
IRS_RE = re.compile(r"\b(\d{2}-\d{7}|\d{9})\b")

TEMPLATE_LABEL_ALT = build_alternation(TEMPLATE_LABELS, auto_escape=True)
CLEAN_TEMPLATE_RE = re.compile(rf"\((?:{TEMPLATE_LABEL_ALT})\)", re.IGNORECASE)

CITY_MATCH_RE = re.compile(r"(?:[,\n]|^)\s*([A-Za-z\s\.\-]+),?\s*$")
NAME_MATCH_RE = re.compile(r"Reporting Person(?:\(s\))?\*?\s*(.+?)(?:\(Last\)|\n|$)")
STREET_MATCH_RE = re.compile(r"(?:\(Middle\)\s*|\n)(.+?)(?:\(Street\)|\n)")
TITLE_MATCH_RE = re.compile(r"Description\s*([^\n]+)", re.IGNORECASE)

STREET_ANCHOR_ALT = build_alternation(STREET_ANCHOR_TERMS, auto_escape=True)
STREET_ANCHOR_RE = re.compile(rf"\b(?:{STREET_ANCHOR_ALT})\b", re.IGNORECASE)

SYMBOL_ALT = build_alternation(SYMBOL_TERMS, auto_escape=True)
SYMBOL_TAIL_RE = re.compile(
    rf"\b(?:{SYMBOL_ALT})\s*:?\s*(.+)$",
    re.IGNORECASE,
)

EXCHANGE_PREFIX_ALT = build_alternation(
    EXCHANGE_PREFIX_TERMS,
    auto_escape=True,
)
TICKER_PAREN_RE = re.compile(
    rf"\s*\((?:(?:{EXCHANGE_PREFIX_ALT})\s*:\s*)?(?:[\"“”']\s*)?([A-Za-z0-9\.\-]+(?:\s+and\s+[A-Za-z0-9\.\-]+)?)(?:\s*[\"“”'])?\)\s*$",
    re.IGNORECASE,
)
TICKER_DASH_RE = re.compile(r"\s+[—\-]\s+([A-Za-z0-9]{1,6})\s*$")

ISSUER_TAIL_TERMS = ("issuer name and ticker", "issuer name", "issuer")
ISSUER_TAIL_ALT = build_alternation(ISSUER_TAIL_TERMS, auto_escape=True)
ISSUER_TAIL_RE = re.compile(
    rf"\b(?:{ISSUER_TAIL_ALT})\s*:\s*(.+)$",
    re.IGNORECASE,
)

NON_OWNER_JURISDICTION_ALT = build_alternation(
    NON_OWNER_JURISDICTION_TERMS, auto_escape=True
)
NON_OWNER_JURISDICTION_RE = re.compile(
    rf"^\s*(?:{NON_OWNER_JURISDICTION_ALT})\s*$", re.IGNORECASE
)

STRIP_BOX_NUM_RE = re.compile(r"^\s*(?:\[\d{1,2}\]|\d{1,2}\.)\s*")
BARE_BOX_NUM_RE = re.compile(r"^\s*\d{1,2}\.?\s*$")

__all__ = [
    "BARE_BOX_NUM_RE",
    "CITY_MATCH_RE",
    "CLEAN_TEMPLATE_RE",
    "EXCHANGE_PREFIX_ALT",
    "IRS_RE",
    "ISSUER_LABEL_TERMS",
    "ISSUER_TAIL_ALT",
    "ISSUER_TAIL_RE",
    "ISSUER_TAIL_TERMS",
    "NAME_MATCH_RE",
    "NON_OWNER_JURISDICTION_ALT",
    "NON_OWNER_JURISDICTION_RE",
    "STATE_ALT",
    "STATE_ZIP_RE",
    "STREET_ANCHOR_ALT",
    "STREET_ANCHOR_RE",
    "STREET_MATCH_RE",
    "STRIP_BOX_NUM_RE",
    "SYMBOL_ALT",
    "SYMBOL_TAIL_RE",
    "TEMPLATE_LABEL_ALT",
    "TICKER_DASH_RE",
    "TICKER_PAREN_RE",
    "TITLE_MATCH_RE",
]
