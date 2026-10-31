"""Shared domain vocabulary for reporting persons, issuers, and addresses."""

from __future__ import annotations

TEMPLATE_LABELS: tuple[str, ...] = (
    "Last",
    "First",
    "Middle",
    "Street",
    "City",
    "State",
    "Zip",
)

ISSUER_LABEL_TERMS: tuple[str, ...] = (
    "issuer name",
    "trading symbol",
    "ticker symbol",
    "and ticker",
    "or trading",
)

SYMBOL_TERMS: tuple[str, ...] = (
    "trading symbol",
    "ticker symbol",
    "symbol",
)

EXCHANGE_PREFIX_TERMS: tuple[str, ...] = (
    "nasdaq",
    "nyse",
    "amex",
)

NON_OWNER_JURISDICTION_TERMS: tuple[str, ...] = (
    "usa",
    "u.s.a.",
    "united states",
)

STREET_TYPE_SUFFIXES: tuple[str, ...] = (
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
    "parkway",
    "pkwy",
    "highway",
    "hwy",
    "broadway",
    "route",
    "rt",
    "terrace",
    "ter",
    "place",
    "pl",
    "alley",
    "aly",
    "turnpike",
    "tpke",
    "run",
    "loop",
)

SECONDARY_UNIT_DESIGNATORS: tuple[str, ...] = (
    "suite",
    "ste",
    "floor",
    "fl",
    "building",
    "bldg",
    "penthouse",
    "ph",
    "apartment",
    "apt",
    "unit",
    "room",
    "rm",
    "department",
    "dept",
    "tower",
    "hall",
    "level",
)

POSTAL_BOX_DESIGNATORS: tuple[str, ...] = (
    "p.o. box",
    "po box",
    "post office box",
    "c/o",
    "box",
)

CAMPUS_COMPLEX_ANCHORS: tuple[str, ...] = (
    "plaza",
    "plz",
    "center",
    "ctr",
    "park",
    "campus",
    "one",
    "two",
    "three",
)

STREET_ANCHOR_TERMS: tuple[str, ...] = (
    *STREET_TYPE_SUFFIXES,
    *SECONDARY_UNIT_DESIGNATORS,
    *POSTAL_BOX_DESIGNATORS,
    *CAMPUS_COMPLEX_ANCHORS,
)

CANONICAL_EXCHANGE_NAMES: tuple[str, ...] = (
    "NYSE",
    "NASDAQ",
    "AMEX",
    "OTC",
    "CBOE",
    "BATS",
    "ARCA",
    "OTCQX",
    "OTCQB",
    "IEX",
    "PHLX",
)

EXCHANGE_ALIASES: dict[str, str] = {
    "NASDQ": "NASDAQ",
    "NASD": "NASDAQ",
    "NQB": "OTCQB",
    "N.Y.S.E.": "NYSE",
    "NEW YORK STOCK EXCHANGE": "NYSE",
    "NYSE AMERICAN": "AMEX",
    "NYSE ARCA": "ARCA",
    "NASDAQ CAPITAL MARKET": "NASDAQ",
    "NASDAQ GLOBAL MARKET": "NASDAQ",
    "NASDAQ GLOBAL SELECT": "NASDAQ",
    "OVER THE COUNTER": "OTC",
    "OTC PINK": "OTC",
    "OTCPK": "OTC",
    "PINK SHEETS": "OTC",
}

MIC_TO_EXCHANGE: dict[str, str] = {
    "XNYS": "NYSE",
    "XNAS": "NASDAQ",
    "XASE": "AMEX",
    "ARCX": "ARCA",
    "BATS": "BATS",
    "IEXG": "IEX",
    "XCBO": "CBOE",
}

TABULAR_STOPWORDS: tuple[str, ...] = (
    "the",
    "of",
    "and",
    "to",
    "in",
    "or",
    "is",
    "for",
    "by",
    "be",
    "as",
    "on",
    "with",
    "that",
    "this",
    "from",
    "at",
    "an",
    "are",
    "it",
    "if",
    "not",
    "any",
    "which",
    "such",
    "other",
    "all",
    "shall",
    "has",
    "have",
    "been",
    "thereof",
)

INSTRUCTION_SIGNATURE_PHRASES: tuple[str, ...] = (
    "whose account the securities are to be sold",
    "through whom the securities are intended",
    "securities intended to be sold",
    "if debt securities",
    "face amount thereof",
    "see instruction",
    "see instr",
    "instructions to filer",
    "nature of the consideration given",
    "payment therefor was not made in cash",
    "note or other obligation",
    "discharged in full",
    "last installment paid",
    "potential persons who are to respond",
    "valid omb control number",
    "burden hours per response",
    "18 u.s.c. 1001",
    "intentional misstatements",
    "criminal violations",
    "regulation s-t",
    "filed pursuant to section 16",
    "section 16(a)",
    "subject to section 16",
    "statement of changes in beneficial ownership",
)

RELATIONSHIP_TO_ISSUER_TERMS: tuple[str, ...] = (
    "director",
    "officer",
    "executive officer",
    "10% owner",
    "10% stockholder",
    "promoter",
    "immediate family",
    "beneficial owner",
)

OFFICER_TITLE_TERMS: tuple[str, ...] = (
    "chief executive officer",
    "ceo",
    "chief financial officer",
    "cfo",
    "chief operating officer",
    "coo",
    "president",
    "vice president",
    "executive vice president",
    "senior vice president",
    "secretary",
    "treasurer",
    "general counsel",
    "director",
    "officer",
    "controller",
)

PII_MASK_TERMS: tuple[str, ...] = (
    "###-##-####",
    "##-#######",
    "00-0000000",
    "applied for",
    "none",
    "n/a",
    "unknown",
)

PHONE_LABEL_TERMS: tuple[str, ...] = (
    "telephone",
    "telephone no",
    "tel",
    "tel no",
    "phone",
    "area code",
    "including area code",
)

FOOTNOTE_PREFIX_TERMS: tuple[str, ...] = (
    "see footnote",
    "see note",
    "footnote",
    "note",
)

ENTITY_NUMERIC_EXCEPTIONS: tuple[str, ...] = (
    "401(k)",
    "series a",
    "series b",
    "series c",
    "class a",
    "class b",
)

SEC_FILE_NUMBER_PREFIXES: tuple[str, ...] = (
    "000",
    "001",
    "002",
    "005",
    "028",
    "033",
    "333",
)

__all__ = [
    "CAMPUS_COMPLEX_ANCHORS",
    "CANONICAL_EXCHANGE_NAMES",
    "ENTITY_NUMERIC_EXCEPTIONS",
    "EXCHANGE_ALIASES",
    "EXCHANGE_PREFIX_TERMS",
    "FOOTNOTE_PREFIX_TERMS",
    "INSTRUCTION_SIGNATURE_PHRASES",
    "ISSUER_LABEL_TERMS",
    "MIC_TO_EXCHANGE",
    "NON_OWNER_JURISDICTION_TERMS",
    "OFFICER_TITLE_TERMS",
    "PHONE_LABEL_TERMS",
    "PII_MASK_TERMS",
    "POSTAL_BOX_DESIGNATORS",
    "RELATIONSHIP_TO_ISSUER_TERMS",
    "SECONDARY_UNIT_DESIGNATORS",
    "SEC_FILE_NUMBER_PREFIXES",
    "STREET_ANCHOR_TERMS",
    "STREET_TYPE_SUFFIXES",
    "SYMBOL_TERMS",
    "TABULAR_STOPWORDS",
    "TEMPLATE_LABELS",
]
