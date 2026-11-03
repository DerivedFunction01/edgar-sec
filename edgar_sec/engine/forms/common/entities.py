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
from edgar_sec.domain.taxonomy.legal_forms import LEGAL_FORMS, has_legal_form
from edgar_sec.engine.forms.common.statutory import is_pure_statutory_boilerplate
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import parse_date

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
COMMISSION_FILE_TOKEN_RE = re.compile(r"[0-9][0-9a-z]*(?:-[0-9a-z]+)+|[0-9]+")

#: Legal-form tokens whose presence marks a cover line as a name line
#: (title-position registrant / issuer detection in family analyzers).
NAME_FORM_TOKENS: tuple[str, ...] = (
    " inc",
    " corp",
    " llc",
    " company",
    " bank",
    " trust",
    " plc",
    " ltd",
    " limited",
    " ag",
    " s.a.",
    " n.v.",
    " partners",
    " holdings",
    " group",
    " fund",
)
CUSIP_RE = re.compile(r"(?i)(?<![0-9A-Z])[0-9A-Z*@#]{9}(?![0-9A-Z])")
_CUSIP_CLEAN_RE = re.compile(r"(?i)^[0-9A-Z*@#]{8,9}$")
CRD_RE = re.compile(r"\b\d{1,9}\b")
_SPACED_CUSIP_RE = re.compile(
    r"\b([0-9A-Z]{5,7}[\s\-]+[0-9A-Z]{1,4}(?:[\s\-]+[0-9A-Z]{1,2})?)\b",
    re.IGNORECASE,
)
_CUSIP_FORM_TAIL_RE = re.compile(r"(?i)\s+(?:SC\s+)?13[DG](?:/[A-Z0-9]+)?\s*$")
_CUSIP_SECURITY_CLASSES = (r"Common\s+Stock", r"Class\s+[A-Z]", r"Ordinary\s+Shares")
_CUSIP_SECURITY_ALT = build_alternation(_CUSIP_SECURITY_CLASSES, auto_escape=False)
_CUSIP_SECURITY_TAIL_RE = re.compile(rf"(?i)\s*[-—–]\s*(?:{_CUSIP_SECURITY_ALT}).*$")
_CUSIP_FOOTNOTE_TAIL_RE = re.compile(r"\s*(?:\*{1,3}|(?:\(\d{1,2}\)|\[\d{1,2}\]))\s*$")
_STREET_WORD_RE = re.compile(
    rf"\b(?:{_NON_COLLIDING_ALT}|{_COLLIDING_ALT})\b", re.IGNORECASE
)


def parse_cusip(value: str | None) -> str | None:
    """Extract and normalize a single CUSIP token from text if present."""
    if not value or len(value.strip()) < 8:
        return None
    val = value.strip()
    if is_street_address_value(val) or is_street_or_address_line(val):
        return None
    if parse_date(val) is not None:
        return None
    val = _CUSIP_FORM_TAIL_RE.sub("", val)
    val = _CUSIP_SECURITY_TAIL_RE.sub("", val)
    val = _CUSIP_FOOTNOTE_TAIL_RE.sub("", val).strip()

    compact = val.replace(" ", "").replace("-", "")
    if _CUSIP_CLEAN_RE.fullmatch(compact) and any(c.isdigit() for c in compact):
        return compact.upper()

    for m in _SPACED_CUSIP_RE.finditer(val):
        clean = m.group(1).replace(" ", "").replace("-", "").upper()
        if (
            len(clean) in (8, 9)
            and any(c.isdigit() for c in clean)
            and is_valid_cusip(clean)
        ):
            return clean

    tokens = list(CUSIP_RE.finditer(val))
    if tokens:
        cand = tokens[0].group(0).upper()
        if any(c.isdigit() for c in cand):
            return cand

    if (
        len(compact) == 10
        and is_valid_cusip(compact[:9], length=9)
        and any(c.isdigit() for c in compact[:9])
    ):
        return compact[:9].upper()

    return None


def extract_cusip_near_caption(text: str, *, window: int = 96) -> str | None:
    """First structurally valid, digit-bearing CUSIP token appearing within
    ``window`` characters after a "cusip" mention in ``text``; the caption
    anchor guards against ordinary nine-letter words passing structurally.
    """
    lowered = text.lower()
    position = lowered.find("cusip")
    while position != -1:
        for match in CUSIP_RE.finditer(text[position : position + window]):
            candidate = match.group(0)
            if any(ch.isdigit() for ch in candidate) and is_valid_cusip(candidate):
                return candidate.upper()
        position = lowered.find("cusip", position + 1)
    return None


_REGISTRATION_NO_ALT = build_alternation((r"no\.?", r"nos\.?", "number"))
_REGISTRATION_CAPTION_ALT = build_alternation(
    (
        r"registration\s+(?:statement\s+)?" + _REGISTRATION_NO_ALT,
        r"files?\s+" + _REGISTRATION_NO_ALT,
    )
)
_REGISTRATION_NUMBER_RE = re.compile(
    r"(?:"
    + _REGISTRATION_CAPTION_ALT
    + r")\s*:?\s*\(?\s*((?:333|33)\s*-\s*\d{3,}(?:-\d{2})?)",
    re.IGNORECASE,
)


def extract_registration_number(text: str) -> str | None:
    """First caption-anchored registration number in ``text``: the filed
    caption variants ("Registration No.", "File No.", "Files Nos.") with
    a 333/33 prefix, which keeps commission file numbers (1-, 001-) out.
    """
    match = _REGISTRATION_NUMBER_RE.search(text)
    return match.group(1).replace(" ", "") if match else None


def is_valid_cusip(value: str | None, *, length: int | None = None) -> bool:
    """Return whether value matches CUSIP character structure."""
    if not value:
        return False
    compact = value.replace(" ", "").replace("-", "")
    if length is not None:
        return len(compact) == length and bool(_CUSIP_CLEAN_RE.fullmatch(compact))
    return bool(_CUSIP_CLEAN_RE.fullmatch(compact))


def is_street_address_value(text: str) -> bool:
    """Detect whether text represents an address rather than a proper name."""
    low = text.lower().strip(" ,.-")
    if low.startswith(("p.o. box", "po box", "p o box")):
        return True
    if STATE_ZIP_RE.search(text):
        return True
    if STREET_NUM_LEAD_RE.match(text) and bool(_STREET_WORD_RE.search(low)):
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


_BOILERPLATE_NAMES = frozenset(
    {
        "instructions",
        "street",
        "city",
        "state",
        "zip code",
        "sec use only",
        "area code number",
        "telephone",
        "name of issuer",
        "address of issuer",
        "relationship to issuer",
        "name of person for whose account the securities are to be sold",
        "names of reporting persons",
        "name of reporting person",
        "reporting persons",
        "reporting person",
        "irs identification nos. of above persons",
        "irs identification no. of above person",
    }
)
_HEADER_WORDS = frozenset(
    {
        "address",
        "account",
        "area",
        "city",
        "code",
        "entities",
        "identification",
        "instructions",
        "issuer",
        "location",
        "name",
        "names",
        "number",
        "of",
        "only",
        "person",
        "persons",
        "reporting",
        "sec",
        "securities",
        "sold",
        "state",
        "street",
        "telephone",
        "the",
        "use",
        "whose",
        "work",
        "zip",
    }
)


def _is_header_token(token: str) -> bool:
    return token in _HEADER_WORDS or (
        len(token) >= 3 and any(word.startswith(token) for word in _HEADER_WORDS)
    )


_PHONE_EXACT_RE = re.compile(r"^\+?[\d\s\-.()]{7,}$")
_INSTRUCTION_PHRASE_ALT = build_alternation(
    (
        "identification number",
        "sec use only",
        "file number",
        "market maker who is",
        "instructions",
        "any of the foregoing",
        "for whose account",
        "entities only",
        "irs identification",
    )
)
_INSTRUCTION_PHRASE_RE = re.compile(rf"(?:{_INSTRUCTION_PHRASE_ALT})", re.I)
_NON_ALNUM_TOKEN_RE = re.compile(r"[^a-zA-Z0-9]+")


def is_boilerplate_entity_name(value: str | None) -> bool:
    """Return whether a value is form instruction boilerplate rather than an entity name."""
    if value is None:
        return False
    if not any(c.isalnum() for c in value):
        return True
    cleaned = FILLER_RUN_RE.sub("", value).strip(" _-\t\r\n")
    if (
        len(cleaned) < 2
        or SSN_REDACTION_MASK_RE.fullmatch(cleaned)
        or _PHONE_EXACT_RE.fullmatch(cleaned)
    ):
        return True
    lowered = cleaned.lower()
    if (
        lowered in _BOILERPLATE_NAMES
        or lowered.startswith("(")
        or lowered.startswith(("p.o. box", "po box", "p o box"))
    ):
        return True
    if _INSTRUCTION_PHRASE_RE.search(lowered):
        return True
    if is_pure_statutory_boilerplate(lowered):
        return True
    if ("rule 144" in lowered or "schedule 13" in lowered) and cleaned[:1].islower():
        return True
    if sum(c.isdigit() for c in cleaned) >= 4 and not (
        has_legal_form(lowered) or any(term in lowered for term in ("plan", "401"))
    ):
        return True
    tokens = [token for token in _NON_ALNUM_TOKEN_RE.split(lowered) if token]
    words = [token for token in tokens if token.isalpha()]
    if not words or len(words) + sum(token.isdigit() for token in tokens) != len(
        tokens
    ):
        return False
    return all(_is_header_token(word) for word in words)


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
    "COMMISSION_FILE_TOKEN_RE",
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
    "NAME_FORM_TOKENS",
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
    "extract_cusip_near_caption",
    "extract_registration_number",
    "is_boilerplate_entity_name",
    "is_street_address_value",
    "is_street_or_address_line",
    "is_valid_cusip",
    "is_valid_entity_name",
    "normalize_exchange_name",
    "parse_cusip",
    "sanitize_document_noise",
    "strip_footnote_markers",
]
