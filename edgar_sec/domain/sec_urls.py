"""Canonical SEC endpoint construction.

EDGAR URL shapes are protocol facts, not transport policy: the same three
prefixes are needed by the submissions engine, the HTTP client, the metadata
pipeline, and the filing catalog. They are declared here in Layer 1 because
every other layer may import downward from ``domain`` -- whereas declaring them
in ``infra`` would make them unreachable to the catalog schemas, which sit
below it.

This module is the only place an EDGAR URL is assembled. The shapes differ in
two ways that are easy to get wrong, so both are normalized here:

* the CIK is zero-padded to ten digits in the submissions URL but rendered as a
  bare integer in archive URLs, matching what EDGAR actually serves;
* the accession is unhyphenated in archive URLs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"

CIK_PADDED_WIDTH = 10


def normalize_cik(cik: str | int) -> str:
    """Return ``cik`` as the zero-padded ten-digit string EDGAR expects."""
    return str(cik).zfill(CIK_PADDED_WIDTH)


def submissions_url(cik: str | int) -> str:
    """Return the canonical submissions metadata document URL for a CIK.

    Accepts a padded or unpadded CIK; both spellings resolve to the same URL,
    so a caller need not normalize first.
    """
    return f"{SEC_SUBMISSIONS_BASE}/CIK{normalize_cik(cik)}.json"


def historical_submissions_url(source_file: str) -> str:
    """Return the canonical URL of a historical submissions file."""
    return f"{SEC_SUBMISSIONS_BASE}/{source_file}"


def archives_url(cik: str | int, accession_number: str, document_name: str) -> str:
    """Return the canonical EDGAR archive document URL.

    The CIK is unpadded and the accession is unhyphenated, which is how the
    archive is addressed. Callers that must tolerate a missing or malformed
    document belong in the engine, not here: this function assumes its inputs
    are already usable and will happily build a nonsense URL otherwise.
    """
    accession_clean = str(accession_number).replace("-", "")
    return f"{SEC_ARCHIVE_BASE}/{int(cik)}/{accession_clean}/{document_name}"


#: ``.../Archives/edgar/data/<cik>/<accession>/<document path>``. The document
#: path keeps embedded slashes and case, so no percent-decoding is applied: the
#: value stays byte-faithful to the observed URL.
_ARCHIVE_URL_RE = re.compile(
    rf"^{re.escape(SEC_ARCHIVE_BASE)}/(?P<archive_cik>\d+)/"
    r"(?P<accession>\d{10,18}?)/(?P<document_path>.+)$"
)


def normalize_accession(accession: str) -> str | None:
    """Return the unhyphenated accession, or None when it is not well formed.

    EDGAR serves both ``0000320193-20-000096`` and ``000032019320000096``; the
    archive path uses the unhyphenated form. Anything that is not 10-18 digits
    once hyphens are removed is not an accession.
    """
    if not accession:
        return None
    compact = str(accession).strip().replace("-", "")
    if not compact.isdigit() or not 10 <= len(compact) <= 18:
        return None
    return compact


def accession_hyphenated(accession: str) -> str:
    """Return the hyphenated accession form EDGAR uses in bundle filenames."""
    canonical = normalize_accession(accession)
    if canonical is None:
        raise ValueError(f"accession must be canonicalizable: {accession!r}")
    if len(canonical) == 18:
        return f"{canonical[:10]}-{canonical[10:12]}-{canonical[12:]}"
    # Non-standard length: fall back to a single split after the filer segment
    # rather than guessing at a shape EDGAR does not use.
    return f"{canonical[:10]}-{canonical[10:]}"


@dataclass(frozen=True, slots=True)
class ArchiveUrlParts:
    """The addressable components of one EDGAR archive document URL."""

    url: str
    archive_cik: str
    accession: str
    document_path: str


def parse_archive_url(url: str | None) -> ArchiveUrlParts | None:
    """Parse an archive document URL, or return None when it is not one.

    Returns None for other hosts, missing segments, and an empty document path.
    """
    if not url:
        return None
    match = _ARCHIVE_URL_RE.match(str(url).strip())
    if match is None:
        return None
    accession = normalize_accession(match.group("accession"))
    if accession is None:
        return None
    document_path = match.group("document_path")
    if not document_path.strip("/"):
        return None
    return ArchiveUrlParts(
        url=str(url).strip(),
        archive_cik=match.group("archive_cik"),
        accession=accession,
        document_path=document_path,
    )


def full_submission_url_for(archive_cik: str, accession: str) -> str:
    """Build the complete SGML submission ``.txt`` bundle URL for an accession.

    Example: ``.../data/320193/000032019320000096/0000320193-20-000096.txt``
    """
    canonical = normalize_accession(accession)
    if canonical is None:
        raise ValueError(f"accession must be canonicalizable: {accession!r}")
    dashed = accession_hyphenated(canonical)
    return archives_url(int(archive_cik), canonical, f"{dashed}.txt")


__all__ = [
    "CIK_PADDED_WIDTH",
    "SEC_ARCHIVE_BASE",
    "SEC_SUBMISSIONS_BASE",
    "ArchiveUrlParts",
    "accession_hyphenated",
    "archives_url",
    "full_submission_url_for",
    "historical_submissions_url",
    "normalize_accession",
    "normalize_cik",
    "parse_archive_url",
    "submissions_url",
]
