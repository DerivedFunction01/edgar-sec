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

STREET_ANCHOR_TERMS: tuple[str, ...] = (
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
    "EXCHANGE_PREFIX_TERMS",
    "ISSUER_LABEL_TERMS",
    "NON_OWNER_JURISDICTION_TERMS",
    "RELATIONSHIP_TO_ISSUER_TERMS",
    "SEC_FILE_NUMBER_PREFIXES",
    "STREET_ANCHOR_TERMS",
    "SYMBOL_TERMS",
    "TEMPLATE_LABELS",
]
