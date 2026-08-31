"""Canonical shared vocabulary for SEC entity names and jurisdictions."""

from __future__ import annotations

import re

from defs.regex import build_alternation

STATE_POSTAL_CODES = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
        "PR",
        "VI",
        "GU",
    }
)

STATE_NAMES = frozenset(
    {
        "alabama",
        "alaska",
        "arizona",
        "arkansas",
        "california",
        "colorado",
        "connecticut",
        "delaware",
        "florida",
        "georgia",
        "hawaii",
        "idaho",
        "illinois",
        "indiana",
        "iowa",
        "kansas",
        "kentucky",
        "louisiana",
        "maine",
        "maryland",
        "massachusetts",
        "michigan",
        "minnesota",
        "mississippi",
        "missouri",
        "montana",
        "nebraska",
        "nevada",
        "new hampshire",
        "new jersey",
        "new mexico",
        "new york",
        "north carolina",
        "north dakota",
        "ohio",
        "oklahoma",
        "oregon",
        "pennsylvania",
        "rhode island",
        "south carolina",
        "south dakota",
        "tennessee",
        "texas",
        "utah",
        "vermont",
        "virginia",
        "washington",
        "west virginia",
        "wisconsin",
        "wyoming",
        "district of columbia",
        "puerto rico",
        "virgin islands",
        "guam",
    }
)

LEGAL_FORMS = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "llc",
        "l.l.c.",
        "lp",
        "l.p.",
        "llp",
        "l.l.p.",
        "plc",
        "p.l.c.",
        "ag",
        "sa",
        "s.a.",
        "nv",
        "bv",
        "gmbh",
        "kgaa",
        "se",
        "srl",
        "pty",
        "pvt",
        "cia",
        "spa",
        "sl",
        "lda",
        "sociedad",
        "anonima",
        "holding",
        "holdings",
        "group",
        "grp",
        "trust",
        "fund",
        "bancorp",
        "bankshares",
    }
)

NAME_STOPWORDS = frozenset(
    {
        "the",
        "of",
        "or",
        "and",
        "&",
        "a",
        "an",
        "as",
        "is",
        "for",
        "by",
        "in",
        "on",
        "at",
        "to",
    }
)

JURISDICTION_RE = re.compile(
    rf"\s*/\s*(?:{build_alternation(sorted(STATE_POSTAL_CODES))})(?:\s*/|\s*$)",
    re.IGNORECASE,
)


def strip_jurisdiction(raw: str) -> str:
    """Remove SEC slash-delimited jurisdiction suffixes from an entity name."""
    return JURISDICTION_RE.sub(" ", raw).strip()


def entity_name_tokens(name: str) -> list[str]:
    """Return normalized lexical tokens without legal forms or stopwords."""
    cleaned = strip_jurisdiction(name).lower()
    tokens = re.findall(r"[a-z0-9]+", cleaned)
    return [
        token
        for token in tokens
        if len(token) > 1 and token not in LEGAL_FORMS and token not in NAME_STOPWORDS
    ]


def clean_entity_name(raw: str) -> str:
    """Normalize whitespace after removing a jurisdiction suffix."""
    return " ".join(strip_jurisdiction(raw).split())


__all__ = [
    "JURISDICTION_RE",
    "LEGAL_FORMS",
    "NAME_STOPWORDS",
    "STATE_NAMES",
    "STATE_POSTAL_CODES",
    "clean_entity_name",
    "entity_name_tokens",
    "strip_jurisdiction",
]
