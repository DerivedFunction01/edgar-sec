"""Compiled regular expression patterns and vocabulary for Form 4 parsing."""

from __future__ import annotations

import re

from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES
from edgar_sec.foundation.regex.builder import build_alternation

STATE_ALT = build_alternation(sorted(STATE_POSTAL_CODES))
STATE_ZIP_RE = re.compile(rf"\b({STATE_ALT})\s+(\d{{5}}(?:-\d{{4}})?)\b")
IRS_RE = re.compile(r"\b(\d{2}-\d{7}|\d{9})\b")

TEMPLATE_LABELS = ("Last", "First", "Middle", "Street", "City", "State", "Zip")
TEMPLATE_LABEL_ALT = build_alternation(TEMPLATE_LABELS, auto_escape=True)
CLEAN_TEMPLATE_RE = re.compile(rf"\((?:{TEMPLATE_LABEL_ALT})\)", re.IGNORECASE)

CITY_MATCH_RE = re.compile(r"(?:[,\n]|^)\s*([A-Za-z\s\.\-]+),?\s*$")
NAME_MATCH_RE = re.compile(r"Reporting Person\*?\s*(.+?)(?:\(Last\)|\n|$)")
STREET_MATCH_RE = re.compile(r"(?:\(Middle\)\s*|\n)(.+?)(?:\(Street\)|\n)")
TITLE_MATCH_RE = re.compile(r"Description\s*([^\n]+)", re.IGNORECASE)

PERIOD_MATCH_RE = re.compile(
    r"Statement for(?:\s*\([^\)]*\))?\s*:?\s*([A-Za-z0-9/,\- ]+)",
    re.IGNORECASE,
)
AMEND_MATCH_RE = re.compile(r"Date of Original[^\n]*\n([^\n]+)", re.IGNORECASE)

BOX5_SPLIT_TERMS = (
    "5. if amendment",
    "5.if amendment",
    "if amendment",
    "date of original",
)
BOX5_SPLIT_ALT = build_alternation(BOX5_SPLIT_TERMS, auto_escape=True)
BOX5_SPLIT_RE = re.compile(rf"(?i)(?:{BOX5_SPLIT_ALT})")

PERIOD_PREFIX_TERMS = (
    r"4\.\s*",
    r"statement\s+for\s*(?:\([^)]*\))?\s*:?\s*",
    r"\(?month\s*/\s*(?:day\s*/\s*)?year\)?\s*:?\s*",
    r"\(?month\s*/\s*year\)?\s*:?\s*",
)
PERIOD_PREFIX_ALT = build_alternation(PERIOD_PREFIX_TERMS, auto_escape=False)
PERIOD_PREFIX_RE = re.compile(rf"(?i)^(?:{PERIOD_PREFIX_ALT})+")

AMEND_LABEL_TERMS = (
    r"5\.\s*if\s+amendment[^\n]*",
    r"5\.if\s+amendment[^\n]*",
    r"if\s+amendment[^\n]*",
    r"date\s+of\s+original[^\n]*",
    r"\(?month\s*/\s*(?:day\s*/\s*)?year\)?",
)
AMEND_LABEL_ALT = build_alternation(AMEND_LABEL_TERMS, auto_escape=False)
AMEND_LABEL_RE = re.compile(rf"(?i)^(?:{AMEND_LABEL_ALT})\s*$")


SIG_NAME_TERMINATOR_ALT = build_alternation(
    [r"\s+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", r"\n", r"$"],
    auto_escape=False,
)
SIG_NAME_RE = re.compile(
    rf"Signature of Reporting Person(?:\s+Date)?\s+([A-Za-z\.\- ]+?)(?:{SIG_NAME_TERMINATOR_ALT})",
    re.IGNORECASE,
)
SIG_PERSON_PREFIX_RE = re.compile(
    r"([A-Za-z\.\- ]{3,40}?)\s*\n?(?:[^\n]*\d{2,4}\s*\n?)?\s*\*{1,2}\s*Signature of Reporting Person",
    re.IGNORECASE,
)

ISSUER_LABEL_TERMS = (
    "issuer name",
    "trading symbol",
    "ticker symbol",
    "and ticker",
    "or trading",
)
SYMBOL_TERMS = ("trading symbol", "ticker symbol", "symbol")
SYMBOL_ALT = build_alternation(SYMBOL_TERMS, auto_escape=True)
SYMBOL_TAIL_RE = re.compile(
    rf"\b(?:{SYMBOL_ALT})\s*:?\s*(.+)$",
    re.IGNORECASE,
)
EXCHANGE_PREFIX_ALT = build_alternation(
    ["nasdaq", "nyse", "amex"],
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
STRIP_BOX_NUM_RE = re.compile(r"^\s*(?:\[\d{1,2}\]|\d{1,2}\.)\s*")
BARE_BOX_NUM_RE = re.compile(r"^\s*\d{1,2}\.?\s*$")
AMEND_DATE_CLEAN_RE = re.compile(
    r"^(?:5\.\s*|date\s+of\s+original\s*:?\s*)", re.IGNORECASE
)

STREET_ANCHOR_TERMS = (
    "street",
    "st",
    "avenue",
    "ave",
    "boulevard",
    "blvd",
    "road",
    "rd",
    "drive",
    "dr",
    "lane",
    "ln",
    "circle",
    "cir",
    "court",
    "ct",
    "way",
    "plaza",
    "plz",
    "parkway",
    "pkwy",
    "highway",
    "broadway",
    "hwy",
    "route",
    "rt",
    "suite",
    "ste",
    "floor",
    "fl",
    "center",
    "ctr",
    "building",
    "bldg",
    "p.o. box",
    "po box",
    "c/o",
    "penthouse",
    "tower",
    "hall",
    "box",
    "terrace",
    "ter",
    "one",
    "two",
    "three",
)
STREET_ANCHOR_ALT = build_alternation(STREET_ANCHOR_TERMS, auto_escape=True)
STREET_ANCHOR_RE = re.compile(rf"\b(?:{STREET_ANCHOR_ALT})\b", re.IGNORECASE)

PROSE_BOILERPLATE_TERMS = (
    "check this box if no longer subject",
    "form 4 or form 5 obligations",
    "see instruction",
    "washington, d.c.",
    "securities and exchange commission",
    "statement of changes in beneficial ownership",
    "name and address of reporting person",
    "name and address",
    "(print or type responses)",
    "print or type responses",
    "issuer name and ticker",
    "ticker or trading symbol",
    "or trading symbol",
    "trading symbol",
    "i.r.s. identification number",
    "if an entity (voluntary)",
    "statement for month/day/year",
    "if amendment, date of original",
    "relationship of reporting person",
    "individual or joint/group filing",
    "table i - non-derivative",
    "table ii - derivative",
    "reminder: report on a separate line",
    "potential persons who are to respond",
    "*intentional misstatements",
    "**signature of reporting person",
    "person* (last, first, middle)",
    "last, first, middle",
    "(last, first, middle)",
    "if an entity",
    "form 4",
)
PROSE_BOILERPLATE_ALT = build_alternation(PROSE_BOILERPLATE_TERMS, auto_escape=True)
PROSE_BOILERPLATE_RE = re.compile(rf"(?:{PROSE_BOILERPLATE_ALT})", re.IGNORECASE)

NON_OWNER_JURISDICTION_TERMS = ("usa", "u.s.a.", "united states")
NON_OWNER_JURISDICTION_ALT = build_alternation(
    NON_OWNER_JURISDICTION_TERMS, auto_escape=True
)
NON_OWNER_JURISDICTION_RE = re.compile(
    rf"^\s*(?:{NON_OWNER_JURISDICTION_ALT})\s*$", re.IGNORECASE
)

HEADER_LEAK_PHRASES = (
    "deemed execution",
    "date of original",
    "title of security",
    "individual or joint",
    "price of derivative",
    "amount or number",
    "conversion or exercise",
)

SIG_BOILERPLATE_TERMS = (
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

__all__ = [
    "AMEND_DATE_CLEAN_RE",
    "AMEND_LABEL_RE",
    "AMEND_MATCH_RE",
    "BARE_BOX_NUM_RE",
    "BOX5_SPLIT_RE",
    "CITY_MATCH_RE",
    "CLEAN_TEMPLATE_RE",
    "HEADER_LEAK_PHRASES",
    "IRS_RE",
    "ISSUER_LABEL_TERMS",
    "ISSUER_TAIL_RE",
    "NAME_MATCH_RE",
    "NON_OWNER_JURISDICTION_RE",
    "PERIOD_MATCH_RE",
    "PERIOD_PREFIX_RE",
    "PROSE_BOILERPLATE_RE",
    "SIG_BOILERPLATE_TERMS",
    "SIG_NAME_RE",
    "SIG_PERSON_PREFIX_RE",
    "STATE_ZIP_RE",
    "STREET_ANCHOR_RE",
    "STREET_MATCH_RE",
    "STRIP_BOX_NUM_RE",
    "SYMBOL_TAIL_RE",
    "TEMPLATE_LABELS",
    "TICKER_DASH_RE",
    "TICKER_PAREN_RE",
    "TITLE_MATCH_RE",
]
