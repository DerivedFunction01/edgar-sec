"""Canonical SEC endpoint construction.

Two shapes are easy to get wrong and are normalized here: the CIK is zero-padded to
ten digits in a submissions URL but bare in an archive URL, and the archive URL's
accession is unhyphenated.
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

    Accepts a padded or unpadded CIK; both resolve to the same URL.
    """
    return f"{SEC_SUBMISSIONS_BASE}/CIK{normalize_cik(cik)}.json"


def historical_submissions_url(source_file: str) -> str:
    """Return the canonical URL of a historical submissions file."""
    return f"{SEC_SUBMISSIONS_BASE}/{source_file}"


def archives_url(cik: str | int, accession_number: str, document_name: str) -> str:
    """Return the canonical EDGAR archive document URL.

    Inputs are assumed usable and a nonsense URL is built rather than refused;
    tolerating a missing or malformed document belongs in the engine.
    """
    accession_clean = str(accession_number).replace("-", "")
    return f"{SEC_ARCHIVE_BASE}/{int(cik)}/{accession_clean}/{document_name}"


#: The document path keeps embedded slashes and case, so no percent-decoding is
#: applied and the value stays byte-faithful to the observed URL.
_ARCHIVE_URL_RE = re.compile(
    rf"^{re.escape(SEC_ARCHIVE_BASE)}/(?P<archive_cik>\d+)/"
    r"(?P<accession>\d{10,18}?)/(?P<document_path>.+)$"
)


def normalize_accession(accession: str) -> str | None:
    """Return the unhyphenated accession, or None when it is not well formed.

    Anything that is not 10-18 digits once hyphens are removed is not an accession.
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
    # Non-standard length: split once after the filer segment rather than guessing.
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
