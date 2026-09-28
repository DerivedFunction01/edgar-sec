"""Canonical SEC endpoint construction.

EDGAR URL shapes are protocol facts, not transport policy: the same three
prefixes are needed by the submissions engine, the HTTP client, the metadata
pipeline, and the filing catalog. They are declared here in Layer 1 because
every other layer may import downward from ``domain`` -- whereas declaring them
in ``infra`` would make them unreachable to the catalog schemas, which sit
below it.

This module is the only place an EDGAR URL is assembled. The shapes differ in
two ways that previously caused silent divergence, so both are normalized here:

* the CIK is zero-padded to ten digits in the submissions URL but rendered as a
  bare integer in archive URLs, matching what EDGAR actually serves;
* the accession is unhyphenated in archive URLs.
"""

from __future__ import annotations

SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"

CIK_PADDED_WIDTH = 10


def normalize_cik(cik: str | int) -> str:
    """Return ``cik`` as the zero-padded ten-digit string EDGAR expects."""
    return str(cik).zfill(CIK_PADDED_WIDTH)


def submissions_url(cik: str | int) -> str:
    """Return the canonical submissions metadata document URL for a CIK.

    Accepts a padded or unpadded CIK. Two definitions of this function used to
    exist, one of which padded and one of which did not, so the same CIK could
    resolve to two different URLs depending on the caller.
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


__all__ = [
    "CIK_PADDED_WIDTH",
    "SEC_ARCHIVE_BASE",
    "SEC_SUBMISSIONS_BASE",
    "archives_url",
    "historical_submissions_url",
    "normalize_cik",
    "submissions_url",
]
