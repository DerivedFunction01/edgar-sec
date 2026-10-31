"""Compiled regexes and parsers for reporting persons, issuers, and addresses."""

from __future__ import annotations

from functools import lru_cache
import re

from edgar_sec.domain.forms.common.entities import (
    CANONICAL_EXCHANGE_NAMES,
    ENTITY_NUMERIC_EXCEPTIONS,
    EXCHANGE_ALIASES,
    EXCHANGE_PREFIX_TERMS,
    FOOTNOTE_PREFIX_TERMS,
    INSTRUCTION_SIGNATURE_PHRASES,
    ISSUER_LABEL_TERMS,
    NON_OWNER_JURISDICTION_TERMS,
    OFFICER_TITLE_TERMS,
    PHONE_LABEL_TERMS,
    PII_MASK_TERMS,
    POSTAL_BOX_DESIGNATORS,
    RELATIONSHIP_TO_ISSUER_TERMS,
    SECONDARY_UNIT_DESIGNATORS,
    SEC_FILE_NUMBER_PREFIXES,
    STREET_ANCHOR_TERMS,
    STREET_TYPE_SUFFIXES,
    SYMBOL_TERMS,
    TEMPLATE_LABELS,
)
from edgar_sec.domain.taxonomy.jurisdictions import (
    STATE_NAMES,
    STATE_POSTAL_CODES,
    strip_jurisdiction,
)
from edgar_sec.domain.taxonomy.legal_forms import LEGAL_FORMS
from edgar_sec.foundation.regex.builder import build_alternation

STATE_ALT = build_alternation(sorted(STATE_POSTAL_CODES))
_STATE_ZIP_ALT = build_alternation(
    sorted((*STATE_POSTAL_CODES, *STATE_NAMES)), auto_escape=True
)
STATE_ZIP_RE = re.compile(
    rf"\b({_STATE_ZIP_ALT})\s+(\d{{5}}(?:-\d{{4}})?)\b", re.IGNORECASE
)
_INTL_POSTAL_RE = r"[A-Z0-9][A-Z0-9\-]{0,9}(?:\s[A-Z0-9]{1,6})?"
INTERNATIONAL_ADDRESS_RE = re.compile(
    rf"^(?P<city>[^,]+?),\s*(?P<country>[A-Za-z][A-Za-z .'\-]*?)\s+"
    rf"(?P<postal>{_INTL_POSTAL_RE})$",
    re.IGNORECASE,
)
IRS_RE = re.compile(r"\b(\d{2}-\d{7}|\d{9})\b")

EXCHANGE_ALT = build_alternation((*CANONICAL_EXCHANGE_NAMES, *EXCHANGE_ALIASES))
EXCHANGE_RE = re.compile(rf"\b({EXCHANGE_ALT})\b", re.IGNORECASE)


@lru_cache(maxsize=512)
def normalize_exchange_name(text: str) -> str | None:
    """Normalize stock exchange name or alias to canonical form."""
    match = EXCHANGE_RE.search(text)
    if not match:
        return None
    exchange = match.group(1).upper()
    return EXCHANGE_ALIASES.get(exchange, exchange)


_COLLIDING_SUFFIXES = ("ct", "fl")
_NON_COLLIDING_SUFFIXES = tuple(
    s for s in STREET_TYPE_SUFFIXES if s not in _COLLIDING_SUFFIXES
)
_NON_COLLIDING_ALT = build_alternation(_NON_COLLIDING_SUFFIXES, auto_escape=True)
_COLLIDING_ALT = build_alternation(_COLLIDING_SUFFIXES, auto_escape=True)
STREET_SUFFIX_RE = re.compile(
    rf"\b(?:{_NON_COLLIDING_ALT})\.?(?=\s|,|$)|(?:\b(?:{_COLLIDING_ALT})\.?(?!\s+\d{{5}})(?=\s|,|$))",
    re.IGNORECASE,
)


def is_street_or_address_line(text: str) -> bool:
    """Detect whether text contains a street suffix or state/zip address indicator."""
    return bool(STREET_SUFFIX_RE.search(text) or STATE_ZIP_RE.search(text))


TEMPLATE_LABEL_ALT = build_alternation(TEMPLATE_LABELS, auto_escape=True)
CLEAN_TEMPLATE_RE = re.compile(rf"\((?:{TEMPLATE_LABEL_ALT})\)", re.IGNORECASE)

CITY_MATCH_RE = re.compile(r"(?:[,\n]|^)\s*([A-Za-z\s\.\-]+),?\s*$")
NAME_MATCH_RE = re.compile(r"Reporting Person(?:\(s\))?\*?\s*(.+?)(?:\(Last\)|\n|$)")
STREET_MATCH_RE = re.compile(r"(?:\(Middle\)\s*|\n)(.+?)(?:\(Street\)|\n)")
TITLE_LABEL_TERMS = (
    r"Description\s*",
    r"(?:(?:give\s+)?title\s+below|specify\s+below)\)?\s*(?:[^\n]*\n\s*){0,2}",
)
TITLE_LABEL_ALT = build_alternation(TITLE_LABEL_TERMS, auto_escape=False)
TITLE_MATCH_RE = re.compile(rf"(?:{TITLE_LABEL_ALT})([A-Za-z][^\n]+)", re.IGNORECASE)

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
    rf"\s*\((?:(?:{EXCHANGE_PREFIX_ALT})\s*:\s*)?(?:[\"“”'‘’]+\s*)?([A-Za-z0-9\.\-]+(?:\s+and\s+[A-Za-z0-9\.\-]+)?)(?:\s*[\"“”'‘’]+)?\)\s*$",
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
PAREN_BOX_NUM_RE = re.compile(r"^\s*\(\d{1,2}\)\.?\s*$")

RELATIONSHIP_TO_ISSUER_ALT = build_alternation(
    RELATIONSHIP_TO_ISSUER_TERMS, auto_escape=True
)
RELATIONSHIP_TO_ISSUER_RE = re.compile(
    rf"\b(?:{RELATIONSHIP_TO_ISSUER_ALT})\b", re.IGNORECASE
)

OFFICER_TITLE_ALT = build_alternation(OFFICER_TITLE_TERMS, auto_escape=True)
OFFICER_TITLE_BOUNDARY_RE = re.compile(rf"\b(?:{OFFICER_TITLE_ALT})\b", re.IGNORECASE)

ORGANIZATION_SUFFIX_ALT = build_alternation(sorted(LEGAL_FORMS), auto_escape=True)
ORGANIZATION_SUFFIX_RE = re.compile(
    rf"\b(?:{ORGANIZATION_SUFFIX_ALT})\.?\s*$", re.IGNORECASE
)

STREET_NUM_LEAD_RE = re.compile(r"^\d+\s+[A-Za-z]")

_SUITE_OR_PO_BOX_TERMS = (
    r"p\.?o\.?\s*box\s*\d+",
    r"suite\s*\w+",
    r"floor\s*\w+",
    r"\d+th\s+floor",
    r"level\s+\d+",
    r"bldg\s*\w+",
    r"building\s*\w+",
    r"dept\s*\w+",
    r"unit\s*\w+",
    r"room\s*\w+",
)
SUITE_OR_PO_BOX_ALT = build_alternation(_SUITE_OR_PO_BOX_TERMS, auto_escape=False)
SUITE_OR_PO_BOX_RE = re.compile(rf"\b(?:{SUITE_OR_PO_BOX_ALT})\b", re.IGNORECASE)

SSN_REDACTION_MASK_RE = re.compile(r"^#+[-#]+$")
PHONE_NUMBER_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
FILLER_RUN_RE = re.compile(r"_{2,}|-{3,}|={3,}|~{3,}|\.{4,}")
TABLE_BORDER_PIPE_RE = re.compile(r"^\s*\||\|\s*$")
TRAILING_FOOTNOTE_RE = re.compile(
    r"(?:(?<=[a-zA-Z0-9\.\'\"])\s*(?:\[\d{1,2}\]|\(\d{1,2}\)|\*{1,3}|†|‡)|(?<=[a-zA-Z])\s*\d{1,2})\s*$"
)

_WHITESPACE_COLLAPSE_RE = re.compile(r"\s+")

SEC_FILE_PREFIX_ALT = build_alternation(SEC_FILE_NUMBER_PREFIXES, auto_escape=True)
SEC_FILE_NUMBER_RE = re.compile(
    rf"\b(?:{SEC_FILE_PREFIX_ALT})-\d{{4,8}}\b", re.IGNORECASE
)
CUSIP_RE = re.compile(r"\b[0-9A-Z]{9}\b")
CRD_RE = re.compile(r"\b\d{1,9}\b")


def is_street_address_value(text: str) -> bool:
    """Detect whether text represents an address rather than a proper name."""
    low = text.lower().strip(" ,.-")
    if low.startswith(("p.o. box", "po box", "p o box")):
        return True
    if STATE_ZIP_RE.search(text):
        return True
    if STREET_NUM_LEAD_RE.match(text) and any(
        term in low
        for term in (
            "street",
            "st",
            "st.",
            "avenue",
            "ave",
            "ave.",
            "road",
            "rd",
            "blvd",
            "boulevard",
            "lane",
            "ln",
            "way",
            "drive",
            "dr",
        )
    ):
        return True
    if bool(SUITE_OR_PO_BOX_RE.search(text)):
        return True
    return low.endswith(("street", "avenue", "boulevard", "highway", "parkway"))


def is_valid_entity_name(name: str) -> bool:
    """Validate entity name morphology against bare numbers and jurisdictions."""
    cleaned = strip_jurisdiction(name).strip(" ,.-")
    if len(cleaned) < 2:
        return False
    if NON_OWNER_JURISDICTION_RE.match(cleaned):
        return False
    if cleaned.isdigit():
        return False
    return True


def sanitize_document_noise(text: str) -> str:
    """Strip border pipes, filler character runs, and collapse extra whitespace."""
    no_pipes = TABLE_BORDER_PIPE_RE.sub("", text)
    no_fillers = FILLER_RUN_RE.sub("", no_pipes)
    return _WHITESPACE_COLLAPSE_RE.sub(" ", no_fillers).strip()


def strip_footnote_markers(text: str) -> str:
    """Strip trailing footnote references and brackets."""
    return TRAILING_FOOTNOTE_RE.sub("", text).strip()


__all__ = [
    "BARE_BOX_NUM_RE",
    "CITY_MATCH_RE",
    "CLEAN_TEMPLATE_RE",
    "CRD_RE",
    "CUSIP_RE",
    "EXCHANGE_ALT",
    "EXCHANGE_PREFIX_ALT",
    "EXCHANGE_RE",
    "FILLER_RUN_RE",
    "IRS_RE",
    "ISSUER_LABEL_TERMS",
    "ISSUER_TAIL_ALT",
    "ISSUER_TAIL_RE",
    "ISSUER_TAIL_TERMS",
    "NAME_MATCH_RE",
    "NON_OWNER_JURISDICTION_ALT",
    "NON_OWNER_JURISDICTION_RE",
    "OFFICER_TITLE_ALT",
    "OFFICER_TITLE_BOUNDARY_RE",
    "ORGANIZATION_SUFFIX_ALT",
    "ORGANIZATION_SUFFIX_RE",
    "PAREN_BOX_NUM_RE",
    "PHONE_NUMBER_RE",
    "RELATIONSHIP_TO_ISSUER_ALT",
    "RELATIONSHIP_TO_ISSUER_RE",
    "SEC_FILE_NUMBER_RE",
    "SEC_FILE_PREFIX_ALT",
    "SSN_REDACTION_MASK_RE",
    "STATE_ALT",
    "STATE_ZIP_RE",
    "STREET_ANCHOR_ALT",
    "STREET_ANCHOR_RE",
    "STREET_MATCH_RE",
    "STREET_NUM_LEAD_RE",
    "STREET_SUFFIX_RE",
    "STRIP_BOX_NUM_RE",
    "SUITE_OR_PO_BOX_ALT",
    "SUITE_OR_PO_BOX_RE",
    "SYMBOL_ALT",
    "SYMBOL_TAIL_RE",
    "TABLE_BORDER_PIPE_RE",
    "TEMPLATE_LABEL_ALT",
    "TICKER_DASH_RE",
    "TICKER_PAREN_RE",
    "TITLE_MATCH_RE",
    "TRAILING_FOOTNOTE_RE",
    "is_street_address_value",
    "is_street_or_address_line",
    "is_valid_entity_name",
    "normalize_exchange_name",
    "sanitize_document_noise",
    "strip_footnote_markers",
]
