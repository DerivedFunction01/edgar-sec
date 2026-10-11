"""Single canonical source of truth for SEC forms vocabulary and patterns."""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

_SECURITIES_REGISTRATION_TERMS = (
    "securities registered pursuant to section 12(b)",
    "securities registered pursuant to section 12(g)",
    "securities registered under section 12",
)
_REGISTRANT_CHARTER_TERM = "exact name of registrant"
_SMALL_BUSINESS_ISSUER_TERM = "name of small business issuer"
_PRINCIPAL_OFFICE_ADDRESS_TERM = "address of principal executive offices"
_EMPLOYER_ID_TERM = "employer identification no."

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
        _EMPLOYER_ID_TERM,
        "taxpayer identification number",
        "i.r.s. no.",
        "irs no.",
    ),
    "principal_address": (
        _PRINCIPAL_OFFICE_ADDRESS_TERM,
        "address of principal executive office",
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
        _REGISTRANT_CHARTER_TERM,
        "name of registrant",
        "translation of registrant's name into english",
        "name of small business issuer as specified in its charter",
        _SMALL_BUSINESS_ISSUER_TERM,
    ),
    "commission_file_number": (
        "commission file number",
        "sec file number",
        "file number",
    ),
    "securities_12b": (
        "securities registered pursuant to section 12(b) of the act",
        *_SECURITIES_REGISTRATION_TERMS,
        "title of each class",
        "title of class",
        "trading symbol(s)",
        "name of each exchange on which registered",
        "par value",
    ),
}

COVER_LABELS_FLAT: tuple[str, ...] = tuple(
    phrase for phrases in COVER_LABELS.values() for phrase in phrases
)

COMMON_SHARES_PHRASES: tuple[str, ...] = (
    "indicate the number of shares outstanding of each of the registrant's classes of common stock",
    "indicate the number of shares outstanding of each of the issuer's classes of common stock",
    "indicate the number of shares outstanding of each of the registrant's classes of common stock as of",
    "indicate the number of shares outstanding of each of the issuer's classes of common stock as of",
    "indicate the number of shares outstanding of each of the registrant's classes of common equity",
    "indicate the number of shares outstanding of each of the issuer's classes of common equity",
    "number of shares of common stock outstanding",
    "shares of common stock outstanding",
    "number of shares of common stock",
    "number of shares outstanding",
    "shares of the issuer",
    "par value outstanding",
    "shares outstanding",
)


_FORM_PATTERN = re.compile(
    r"\b(?:FORM|SCHEDULE)\s+([A-Z0-9]+(?:[-/][A-Z0-9]+)*)\b", re.IGNORECASE
)
COVER_START_IDENTITY_TERMS: tuple[str, ...] = (
    _FORM_PATTERN.pattern,
    r"securities\s+and\s+exchange\s+commission",
)


LARGE_ACCELERATED_FILER: str = "large accelerated filer"
ACCELERATED_FILER: str = "accelerated filer"
NON_ACCELERATED_FILER: str = "non-accelerated filer"
SMALLER_REPORTING_COMPANY: str = "smaller reporting company"
EMERGING_GROWTH_COMPANY: str = "emerging growth company"
SHELL_COMPANY: str = "shell company"
WELL_KNOWN_SEASONED_ISSUER: str = "well-known seasoned issuer"
VOLUNTARY_FILER: str = "voluntary filer"


REPORT_PERIOD_GROUP = "report_period"
FILER_STATUS_GROUP = "filer_status"
STATUTORY_BINARY_GROUP = "statutory_binary"

FILER_LARGE_ACCELERATED = "large_accelerated_filer"
FILER_ACCELERATED = "accelerated_filer"
FILER_NON_ACCELERATED = "non_accelerated_filer"
FILER_SMALLER_REPORTING = "smaller_reporting_company"
FILER_EMERGING_GROWTH = "emerging_growth_company"

FILER_TYPE_LABELS: dict[str, tuple[str, ...]] = {
    FILER_LARGE_ACCELERATED: (LARGE_ACCELERATED_FILER,),
    FILER_ACCELERATED: (ACCELERATED_FILER,),
    FILER_NON_ACCELERATED: (NON_ACCELERATED_FILER, "non accelerated filer"),
    FILER_SMALLER_REPORTING: (SMALLER_REPORTING_COMPANY,),
    FILER_EMERGING_GROWTH: (EMERGING_GROWTH_COMPANY,),
}

STAT_WKSI = "well_known_seasoned_issuer"
STAT_SHELL = "shell_company"
STAT_VOLUNTARY = "voluntary_filer"
STAT_COMPLIANT_12_MONTHS = "compliant_12_months"
STAT_SOX_404B = "sox_404b"
STAT_EGC_TRANSITION_OPTOUT = "egc_transition_optout"
STAT_ERROR_CORRECTION = "error_correction"
STAT_RECOVERY_ANALYSIS = "recovery_analysis"

_FILER_LABEL_TERMS = (
    *(labels[0] for labels in FILER_TYPE_LABELS.values()),
    SHELL_COMPANY,
    WELL_KNOWN_SEASONED_ISSUER,
    VOLUNTARY_FILER,
)
AUDITOR_ATTESTATION_TERM = "auditor attestation"
PRECEDING_12_MONTHS_TERM = "preceding 12 months"
REQUIRED_REPORTS_TERM = "has filed all reports required"
NOT_REQUIRED_TO_FILE_TERM = "not required to file reports"
ERROR_CORRECTION_TERM = "error correction"
RECOVERY_ANALYSIS_TERM = "recovery analysis"

FILER_STATUS_TERMS: tuple[str, ...] = (
    *_FILER_LABEL_TERMS,
    "indicate by check mark",
    AUDITOR_ATTESTATION_TERM,
)


COVER_EVIDENCE_TERMS: tuple[str, ...] = (
    *_FILER_LABEL_TERMS,
    *_SECURITIES_REGISTRATION_TERMS,
    "for the fiscal year ended",
    "for the quarterly period ended",
    "for the transition period",
    _REGISTRANT_CHARTER_TERM,
    _SMALL_BUSINESS_ISSUER_TERM,
    "state or other jurisdiction",
    _EMPLOYER_ID_TERM,
    _PRINCIPAL_OFFICE_ADDRESS_TERM,
    "trading symbol",
    "securities exchange act of 1934",
    "exchange act of 1934",
    "securities act of 1933",
    REQUIRED_REPORTS_TERM,
    PRECEDING_12_MONTHS_TERM,
    "past 90 days",
    "subject to such filing requirements",
    NOT_REQUIRED_TO_FILE_TERM,
    "interactive data file",
)

STATE_INCORPORATION_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['state_of_incorporation'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
    re.IGNORECASE,
)
ADDRESS_RE = re.compile(
    rf"\(?\s*{build_alternation(COVER_LABELS['principal_address'], auto_escape=True, compact=False, flexible_whitespace=True)}\s*\)?",
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
__all__ = [
    "ACCELERATED_FILER",
    "ADDRESS_RE",
    "AUDITOR_ATTESTATION_TERM",
    "COMMISSION_FILE_RE",
    "COVER_EVIDENCE_TERMS",
    "COVER_LABELS",
    "COVER_LABELS_FLAT",
    "COVER_START_IDENTITY_TERMS",
    "EMERGING_GROWTH_COMPANY",
    "ERROR_CORRECTION_TERM",
    "FILER_ACCELERATED",
    "FILER_EMERGING_GROWTH",
    "FILER_LARGE_ACCELERATED",
    "FILER_NON_ACCELERATED",
    "FILER_SMALLER_REPORTING",
    "FILER_STATUS_GROUP",
    "FILER_STATUS_TERMS",
    "FILER_TYPE_LABELS",
    "LARGE_ACCELERATED_FILER",
    "NON_ACCELERATED_FILER",
    "NOT_REQUIRED_TO_FILE_TERM",
    "PRECEDING_12_MONTHS_TERM",
    "RECOVERY_ANALYSIS_TERM",
    "REGISTRANT_NAME_RE",
    "REQUIRED_REPORTS_TERM",
    "REPORT_PERIOD_GROUP",
    "SECURITIES_12B_RE",
    "SHELL_COMPANY",
    "SMALLER_REPORTING_COMPANY",
    "STATE_INCORPORATION_RE",
    "STATUTORY_BINARY_GROUP",
    "STAT_COMPLIANT_12_MONTHS",
    "STAT_EGC_TRANSITION_OPTOUT",
    "STAT_ERROR_CORRECTION",
    "STAT_RECOVERY_ANALYSIS",
    "STAT_SHELL",
    "STAT_SOX_404B",
    "STAT_VOLUNTARY",
    "STAT_WKSI",
    "VOLUNTARY_FILER",
    "WELL_KNOWN_SEASONED_ISSUER",
]
