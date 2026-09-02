"""Single canonical source of truth for SEC forms vocabulary and patterns.

Contains core cover label tuples, SEC header terms, filer category definitions,
checkbox patterns, and universal contact and layout regexes shared across all
SEC forms.
"""

from __future__ import annotations

import re

from defs.regex import build_alternation

# --- Canonical Cover Label Aliases ---------------------------------------------

COVER_LABELS: dict[str, tuple[str, ...]] = {
    "state_of_incorporation": (
        "state or other jurisdiction of incorporation or organization",
        "state or other jurisdiction of incorporation",
        "jurisdiction of incorporation",
        "state of incorporation",
        "state of organization",
    ),
    "irs_ein": (
        "i.r.s. employer identification no.",
        "irs employer identification no.",
        "employer identification number",
        "employer identification no.",
        "taxpayer identification number",
        "i.r.s. no.",
        "irs no.",
    ),
    "principal_address": (
        "address of principal executive offices",
        "principal executive offices",
    ),
    "zip_code": (
        "zip code",
        "postal code",
        "zip",
        "postal",
    ),
    "telephone": (
        "registrant's telephone number, including area code",
        "registrant telephone number, including area code",
        "issuer's telephone number, including area code",
        "issuer's telephone number",
        "issuer s telephone number",
        "telephone number, including area code",
        "telephone number",
        "including area code",
    ),
    "registrant_name": (
        "exact name of registrant as specified in its charter",
        "name of registrant as specified in its charter",
        "exact name of registrant",
        "name of registrant",
        "name of small business issuer as specified in its charter",
        "name of small business issuer",
    ),
    "commission_file_number": (
        "commission file number",
        "sec file number",
        "file number",
    ),
    "securities_12b": (
        "securities registered pursuant to section 12(b) of the act",
        "securities registered pursuant to section 12(b)",
        "securities registered pursuant to section 12(g)",
        "securities registered under section 12",
        "title of each class",
        "title of class",
        "trading symbol(s)",
        "name of each exchange on which registered",
        "par value",
    ),
}

# Flattened list of all canonical cover labels (longest first).
COVER_LABELS_FLAT: tuple[str, ...] = tuple(
    phrase for phrases in COVER_LABELS.values() for phrase in phrases
)

# --- Standard SEC Header Terms -------------------------------------------------

SEC_HEADER_TERMS: tuple[str, ...] = (
    "securities and exchange commission",
    "washington, d.c.",
    "washington d.c.",
    "united states",
)

COVER_START_IDENTITY_TERMS: tuple[str, ...] = (
    rf"form\s+{build_alternation(['10-k', '20-f', '10-q', '8-k', '6-k'], auto_escape=True)}",
    r"securities\s+and\s+exchange\s+commission",
)

# --- Filer Status Category Constants -------------------------------------------

LARGE_ACCELERATED_FILER: str = "large accelerated filer"
ACCELERATED_FILER: str = "accelerated filer"
NON_ACCELERATED_FILER: str = "non-accelerated filer"
SMALLER_REPORTING_COMPANY: str = "smaller reporting company"
EMERGING_GROWTH_COMPANY: str = "emerging growth company"
SHELL_COMPANY: str = "shell company"
WELL_KNOWN_SEASONED_ISSUER: str = "well-known seasoned issuer"
VOLUNTARY_FILER: str = "voluntary filer"


def _phrase_pattern(term: str) -> str:
    return build_alternation([term], auto_escape=True, flexible_whitespace=True)


FILER_CATEGORY_PATTERNS: tuple[tuple[str, str], ...] = (
    (LARGE_ACCELERATED_FILER.capitalize(), _phrase_pattern(LARGE_ACCELERATED_FILER)),
    (NON_ACCELERATED_FILER.capitalize(), _phrase_pattern(NON_ACCELERATED_FILER)),
    ("Accelerated filer", r"(?<!large\s)" + _phrase_pattern(ACCELERATED_FILER)),
    (
        SMALLER_REPORTING_COMPANY.capitalize(),
        _phrase_pattern(SMALLER_REPORTING_COMPANY),
    ),
    (EMERGING_GROWTH_COMPANY.capitalize(), _phrase_pattern(EMERGING_GROWTH_COMPANY)),
)

# --- Checkbox Keywords & Grids -------------------------------------------------

CHECKBOX_KEYWORDS: tuple[str, ...] = (
    LARGE_ACCELERATED_FILER,
    ACCELERATED_FILER,
    NON_ACCELERATED_FILER,
    SMALLER_REPORTING_COMPANY,
    EMERGING_GROWTH_COMPANY,
    SHELL_COMPANY,
    WELL_KNOWN_SEASONED_ISSUER,
    VOLUNTARY_FILER,
    "yes",
    "no",
    "yes no",
    "check mark if the registrant is",
    "indicate by check mark if",
    "indicate by check mark",
    "check one",
    "check mark",
    "check marks",
    "checkbox",
    "check box",
    "as defined in rule 12b-2",
    "as defined in rule",
    "rule 405 of the securities act",
    "rule 405 of regulation",
    "rule 405",
)

_KW_ALT = build_alternation(
    CHECKBOX_KEYWORDS, auto_escape=True, flexible_whitespace=True
)
_BOX = r"(?:\[[ xX\u2611\u2612\u2610]?\]|[\u2611\u2612\u2610\u25a0\u25a1\u25aa\u25ab\u2713\u2714\u2717\u2718\u00fe\u00fd]|&#9744;|&#9746;|&#9745;|&#9633;|&#9632;|\(?[xX]\)?)"
CHECKBOX_GRID_RE = re.compile(
    rf"(?:{_BOX}\s*{_KW_ALT}|{_KW_ALT}\s*{_BOX})", re.IGNORECASE
)

# --- Evidence Terms for Cover Candidate Detection ------------------------------

COVER_EVIDENCE_TERMS: tuple[str, ...] = (
    LARGE_ACCELERATED_FILER,
    ACCELERATED_FILER,
    NON_ACCELERATED_FILER,
    SMALLER_REPORTING_COMPANY,
    EMERGING_GROWTH_COMPANY,
    SHELL_COMPANY,
    WELL_KNOWN_SEASONED_ISSUER,
    VOLUNTARY_FILER,
    "securities registered pursuant to section 12(b)",
    "securities registered pursuant to section 12(g)",
    "securities registered under section 12",
    "for the fiscal year ended",
    "for the quarterly period ended",
    "for the transition period",
    "exact name of registrant",
    "name of small business issuer",
    "state or other jurisdiction",
    "employer identification no.",
    "address of principal executive offices",
    "trading symbol",
    "securities exchange act of 1934",
    "exchange act of 1934",
    "securities act of 1933",
    "has filed all reports required",
    "preceding 12 months",
    "past 90 days",
    "subject to such filing requirements",
    "not required to file reports",
    "interactive data file",
)

COVER_START_SHAPE_TERMS: tuple[str, ...] = (
    *COVER_EVIDENCE_TERMS,
    "indicate by check mark",
)

CURRENCY_SPACING_RE = re.compile(r"\$\s+(\d)")
PUNCT_SPACING_RE = re.compile(r"\s+([,.;:!?)])")
IXBRL_FACT_RE = re.compile(r"ix:nonFraction", re.IGNORECASE)

# --- Value Matching Patterns ---------------------------------------------------

ZIP_VALUE_RE = re.compile(r"(?<![\d\-])\d{5}(?:-\d{4})?(?!\d)")
EIN_VALUE_RE = re.compile(r"\b\d{2}[\-\s]?\d{7}\b")
COMMISSION_FILE_VALUE_RE = re.compile(r"\b\d{1,3}[\-\s]\d{3,8}(?:[\-\s]\d{2,4})?\b")

# --- Field Label Matching Patterns (Linear Alternation, Not Compacted) ---------

STATE_INCORPORATION_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['state_of_incorporation'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
    re.IGNORECASE,
)
IRS_EIN_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['irs_ein'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
    re.IGNORECASE,
)
ADDRESS_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['principal_address'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
    re.IGNORECASE,
)
ZIP_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['zip_code'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
    re.IGNORECASE,
)
TELEPHONE_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['telephone'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
    re.IGNORECASE,
)
REGISTRANT_NAME_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['registrant_name'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
    re.IGNORECASE,
)
COMMISSION_FILE_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['commission_file_number'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
    re.IGNORECASE,
)
SECURITIES_12B_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['securities_12b'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
    re.IGNORECASE,
)

# --- State Jurisdiction Helper -------------------------------------------------

_US_STATES: frozenset[str] = frozenset(
    [
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
        "ALABAMA",
        "ALASKA",
        "ARIZONA",
        "ARKANSAS",
        "CALIFORNIA",
        "COLORADO",
        "CONNECTICUT",
        "DELAWARE",
        "FLORIDA",
        "GEORGIA",
        "HAWAII",
        "IDAHO",
        "ILLINOIS",
        "INDIANA",
        "IOWA",
        "KANSAS",
        "KENTUCKY",
        "LOUISIANA",
        "MAINE",
        "MARYLAND",
        "MASSACHUSETTS",
        "MICHIGAN",
        "MINNESOTA",
        "MISSISSIPPI",
        "MISSOURI",
        "MONTANA",
        "NEBRASKA",
        "NEVADA",
        "NEW HAMPSHIRE",
        "NEW JERSEY",
        "NEW MEXICO",
        "NEW YORK",
        "NORTH CAROLINA",
        "NORTH DAKOTA",
        "OHIO",
        "OKLAHOMA",
        "OREGON",
        "PENNSYLVANIA",
        "RHODE ISLAND",
        "SOUTH CAROLINA",
        "SOUTH DAKOTA",
        "TENNESSEE",
        "TEXAS",
        "UTAH",
        "VERMONT",
        "VIRGINIA",
        "WASHINGTON",
        "WEST VIRGINIA",
        "WISCONSIN",
        "WYOMING",
        "DISTRICT OF COLUMBIA",
    ]
)


def is_state_value(value: str) -> bool:
    """Return whether ``value`` matches a recognized US state name or postal code."""
    return value.strip().upper() in _US_STATES


__all__ = [
    "ACCELERATED_FILER",
    "ADDRESS_RE",
    "CHECKBOX_GRID_RE",
    "CHECKBOX_KEYWORDS",
    "COMMISSION_FILE_RE",
    "COMMISSION_FILE_VALUE_RE",
    "COVER_EVIDENCE_TERMS",
    "COVER_LABELS",
    "COVER_LABELS_FLAT",
    "COVER_START_IDENTITY_TERMS",
    "COVER_START_SHAPE_TERMS",
    "CURRENCY_SPACING_RE",
    "EIN_VALUE_RE",
    "EMERGING_GROWTH_COMPANY",
    "FILER_CATEGORY_PATTERNS",
    "IRS_EIN_RE",
    "IXBRL_FACT_RE",
    "LARGE_ACCELERATED_FILER",
    "NON_ACCELERATED_FILER",
    "PUNCT_SPACING_RE",
    "REGISTRANT_NAME_RE",
    "SECURITIES_12B_RE",
    "SEC_HEADER_TERMS",
    "SHELL_COMPANY",
    "SMALLER_REPORTING_COMPANY",
    "STATE_INCORPORATION_RE",
    "TELEPHONE_RE",
    "VOLUNTARY_FILER",
    "WELL_KNOWN_SEASONED_ISSUER",
    "ZIP_RE",
    "ZIP_VALUE_RE",
    "is_state_value",
]
