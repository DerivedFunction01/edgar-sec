"""US state and territory postal codes, and jurisdiction-suffix removal.

EDGAR entity names carry an incorporation jurisdiction as a slash-delimited
suffix -- ``APPLE FIXTURE INC/CA`` -- which is not part of the company's identity
and must be removed before names are compared. The code list is the statutory
one; a jurisdiction that is not in it is not stripped, so an unrelated slash
inside a name survives untouched.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

# Statutory US state and territory codes that appear in EDGAR incorporation
# fields.
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

# Alternation is built in sorted order so the compiled pattern is byte-identical
# on every run and across processes.
_STATE_ALTERNATION = build_alternation(sorted(STATE_POSTAL_CODES), auto_escape=True)

# Matches a slash-delimited jurisdiction: either a second slash closes it
# ("INC/CA/") or the suffix runs to end of string ("INC/CA").
JURISDICTION_RE = re.compile(
    rf"\s*/\s*{_STATE_ALTERNATION}(?:\s*/|\s*$)",
    re.IGNORECASE,
)


def strip_jurisdiction(raw: str) -> str:
    """Remove SEC slash-delimited jurisdiction suffixes from an entity name."""
    return JURISDICTION_RE.sub(" ", raw).strip()


def clean_entity_name(raw: str) -> str:
    """Normalize whitespace after removing a jurisdiction suffix."""
    return " ".join(strip_jurisdiction(raw).split())


__all__ = [
    "JURISDICTION_RE",
    "STATE_NAMES",
    "STATE_POSTAL_CODES",
    "clean_entity_name",
    "strip_jurisdiction",
]
