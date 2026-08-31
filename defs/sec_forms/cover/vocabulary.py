"""Canonical cover captions shared by extraction and layout normalization."""

from __future__ import annotations

import re

from defs.entities import STATE_NAMES, STATE_POSTAL_CODES
from defs.regex import build_alternation

COVER_LABELS: dict[str, tuple[str, ...]] = {
    "state_of_incorporation": (
        "state or other jurisdiction of incorporation or organization",
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
    "zip_code": ("zip code", "postal code", "zip", "postal"),
    "telephone": (
        "registrant's telephone number, including area code",
        "registrant telephone number, including area code",
        "telephone number, including area code",
        "telephone number",
    ),
    "registrant_name": (
        "exact name of registrant as specified in its charter",
        "name of registrant as specified in its charter",
        "exact name of registrant",
        "name of registrant",
    ),
    "commission_file_number": (
        "commission file number",
        "sec file number",
        "file number",
    ),
    "securities_12b": (
        "securities registered pursuant to section 12(b) of the act",
        "title of each class",
        "trading symbol(s)",
        "name of each exchange on which registered",
    ),
}

COVER_BOUNDARY_PHRASES = (
    "documents incorporated by reference",
    "table of contents",
    "part i item 1",
)

ZIP_VALUE_RE = re.compile(r"(?<![\d\-])\d{5}(?:-\d{4})?(?!\d)")
EIN_VALUE_RE = re.compile(r"\b\d{2}[\-\s]?\d{7}\b")
COMMISSION_FILE_VALUE_RE = re.compile(r"\b\d{1,3}[\-\s]\d{3,8}(?:[\-\s]\d{2,4})?\b")

STATE_INCORPORATION_RE = re.compile(
    rf"\(?(?:{build_alternation(COVER_LABELS['state_of_incorporation'], auto_escape=True)})\)?",
    re.IGNORECASE,
)
IRS_EIN_RE = re.compile(
    rf"\(?(?:{build_alternation(COVER_LABELS['irs_ein'], auto_escape=True)})\)?",
    re.IGNORECASE,
)
ADDRESS_RE = re.compile(
    rf"\(?(?:{build_alternation(COVER_LABELS['principal_address'], auto_escape=True)})\)?",
    re.IGNORECASE,
)
ZIP_RE = re.compile(
    rf"\(?(?:{build_alternation(COVER_LABELS['zip_code'], auto_escape=True)})\)?",
    re.IGNORECASE,
)
TELEPHONE_RE = re.compile(
    rf"\(?(?:{build_alternation(COVER_LABELS['telephone'], auto_escape=True)})\)?",
    re.IGNORECASE,
)
REGISTRANT_NAME_RE = re.compile(
    rf"\(?(?:{build_alternation(COVER_LABELS['registrant_name'], auto_escape=True)})\)?",
    re.IGNORECASE,
)
COMMISSION_FILE_RE = re.compile(
    rf"\(?(?:{build_alternation(COVER_LABELS['commission_file_number'], auto_escape=True)})\)?",
    re.IGNORECASE,
)
SECURITIES_12B_RE = re.compile(
    rf"\(?(?:{build_alternation(COVER_LABELS['securities_12b'], auto_escape=True)})\)?",
    re.IGNORECASE,
)

PUBLIC_FLOAT_PHRASES = (
    "aggregate market value",
    (
        "aggregate market value of the voting and non-voting common equity held by "
        "non-affiliates of the registrant"
    ),
    "held by non-affiliates of the registrant",
)

SHARES_PHRASES = (
    "number of shares outstanding",
    "shares outstanding",
    (
        "indicate the number of shares outstanding of each of the registrant's "
        "classes of common stock as of"
    ),
    "shares of common stock outstanding as of",
)


def is_state_value(value: str) -> bool:
    """Return whether a normalized cell contains a recognized state value."""
    stripped = value.strip()
    return stripped.lower() in STATE_NAMES or (
        len(stripped) == 2 and stripped.upper() in STATE_POSTAL_CODES
    )


__all__ = [
    "ADDRESS_RE",
    "COMMISSION_FILE_RE",
    "COMMISSION_FILE_VALUE_RE",
    "COVER_BOUNDARY_PHRASES",
    "COVER_LABELS",
    "EIN_VALUE_RE",
    "IRS_EIN_RE",
    "PUBLIC_FLOAT_PHRASES",
    "REGISTRANT_NAME_RE",
    "SECURITIES_12B_RE",
    "SHARES_PHRASES",
    "STATE_INCORPORATION_RE",
    "TELEPHONE_RE",
    "ZIP_RE",
    "ZIP_VALUE_RE",
    "is_state_value",
]
