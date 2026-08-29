"""Canonical SEC filing identity primitives.

Pure, network-free functions shared by the metadata phase (materializer and
future v2 normalizer) and later filing phases (resolution, extraction).

Identity model (see .kilo/plans/1787876926126-filing-identity-and-reuse-plan.md):

- **Filing occurrence** — one observed relationship between a submissions
  source CIK and a filing document, keyed by
  ``(source_cik, accession, document_path)``. The same accession observed from
  another source CIK is a separate occurrence; repeated sightings of the same
  tuple coalesce with provenance.
- **Document locator** — the pre-fetch grouping key
  ``(accession, document_path)``, independent of which CIK URL prefix was
  observed. Identical locator groups fetch one representative document.
- **Accession** — a single canonical 18-digit value (zero-padded, dashes
  stripped). The SEC hyphenated spelling is derived on display and never
  stored.

All hashing uses the repository's canonical JSON encoding so identities are
stable across processes and machines.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from defs.storage import canonical_json

SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"
ACCESSION_LENGTH = 18

_ARCHIVE_URL_RE = re.compile(
    r"^https?://www\.sec\.gov/Archives/edgar/data/"
    r"(?P<archive_cik>[^/]+)/(?P<accession>[^/]+)/(?P<document_path>.+)$"
)
_YEAR_RE = re.compile(r"^(\d{4})(?:-|$)")


def _stable_hash(parts: list) -> str:
    payload = ["filing-identity-v1", *parts]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def normalize_accession(raw: str | None) -> str | None:
    """Return the canonical 18-digit accession, or None when unusable.

    Accepts the SEC hyphenated form (``AAAAAAAAA-BB-CCCCCC``, tolerating
    missing leading zeros per component) or an exact 18-digit value. Anything
    else — empty, non-numeric, wrong component lengths, ambiguous digit runs —
    is invalid and yields None instead of a guess.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace(" ", "")
    if not text:
        return None
    if "-" in text:
        parts = text.split("-")
        if len(parts) != 3:
            return None
        filer, year, sequence = parts
        if not (filer.isdigit() and year.isdigit() and sequence.isdigit()):
            return None
        if len(filer) > 10 or len(year) > 2 or len(sequence) > 6:
            return None
        return filer.zfill(10) + year.zfill(2) + sequence.zfill(6)
    if text.isdigit() and len(text) == ACCESSION_LENGTH:
        return text
    return None


def accession_hyphenated(accession: str) -> str:
    """Derive the SEC hyphenated display form of a canonical accession.

    Raises ValueError when the input is not a canonical 18-digit value; the
    hyphenated spelling is a presentation concern and is never stored.
    """
    if not isinstance(accession, str) or not (
        accession.isdigit() and len(accession) == ACCESSION_LENGTH
    ):
        raise ValueError(f"not a canonical 18-digit accession: {accession!r}")
    return f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"


@dataclass(frozen=True)
class ArchiveUrlParts:
    """Parsed components of one observed archive document URL."""

    url: str
    archive_cik: str
    accession: str  # canonical 18-digit value
    document_path: str  # path after the accession directory, slashes preserved


def parse_archive_url(url: str | None) -> ArchiveUrlParts | None:
    """Parse ``.../Archives/edgar/data/<cik>/<accession>/<document path>``.

    Returns None for anything else (other hosts, missing segments, empty
    document path). The document path keeps embedded slashes (e.g.
    ``xslF345X02/doc3.xml``) and case; no percent-decoding is applied so the
    value stays byte-faithful to the observed URL.
    """
    if not url:
        return None
    match = _ARCHIVE_URL_RE.match(str(url).strip())
    if match is None:
        return None
    accession = normalize_accession(match.group("accession"))
    if accession is None:
        return None
    return ArchiveUrlParts(
        url=str(url).strip(),
        archive_cik=match.group("archive_cik"),
        accession=accession,
        document_path=match.group("document_path"),
    )


def archive_url_for(archive_cik: str, accession: str, document_path: str) -> str:
    """Build an archive document URL from observed components.

    The CIK segment uses the unpadded integer form SEC serves
    (``data/6201/...``). Raises ValueError on non-numeric CIKs, non-canonical
    accessions, or an empty document path.
    """
    cik_text = str(archive_cik).strip()
    if not cik_text.isdigit():
        raise ValueError(f"archive_cik must be numeric: {archive_cik!r}")
    if not accession.isdigit() or len(accession) != ACCESSION_LENGTH:
        raise ValueError(f"accession must be canonical 18 digits: {accession!r}")
    path = str(document_path).strip()
    if not path:
        raise ValueError("document_path is required")
    return f"{SEC_ARCHIVE_BASE}/{int(cik_text)}/{accession}/{path}"


def occurrence_id(source_cik: str, accession: str, document_path: str | None) -> str:
    """Stable identity of one filing occurrence.

    Hash of ``(source_cik, accession, document_path)``. The document path is
    treated as empty when unknown, so a None path and "" produce the same
    identity. Deliberately excludes source array index, filing year, and the
    representative URL.
    """
    canonical = normalize_accession(accession)
    if canonical is None:
        raise ValueError(f"accession must be canonicalizable: {accession!r}")
    if not str(source_cik).strip():
        raise ValueError("source_cik is required")
    return _stable_hash(
        ["occurrence", str(source_cik).strip(), canonical, document_path or ""]
    )


def document_locator_key(accession: str, document_path: str | None) -> str:
    """Stable pre-fetch grouping key for one document candidate.

    Hash of ``(accession, document_path)``. Occurrences sharing this key are
    fetched once; the downloaded ``raw_sha256`` remains the evidence identity.
    """
    canonical = normalize_accession(accession)
    if canonical is None:
        raise ValueError(f"accession must be canonicalizable: {accession!r}")
    return _stable_hash(["locator", canonical, document_path or ""])


def filing_year(date_value: str | None) -> str | None:
    """Four-digit year from a leading ``YYYY`` in an ISO-style date."""
    if not date_value:
        return None
    match = _YEAR_RE.match(str(date_value).strip())
    return match.group(1) if match else None


def fiscal_year(report_date: str | None) -> str | None:
    """Fiscal year derived from the report/period end date when available.

    The accession's two-digit sequence is never a year source; a
    document-derived fallback belongs to the owning extraction phase.
    """
    return filing_year(report_date)


def is_amendment_form(form: str | None) -> bool:
    """True when the SEC form marks an amendment (e.g. ``10-K/A``)."""
    return bool(form) and str(form).strip().upper().endswith("/A")


__all__ = [
    "ACCESSION_LENGTH",
    "SEC_ARCHIVE_BASE",
    "ArchiveUrlParts",
    "accession_hyphenated",
    "archive_url_for",
    "canonical_json",
    "document_locator_key",
    "filing_year",
    "fiscal_year",
    "is_amendment_form",
    "normalize_accession",
    "occurrence_id",
    "parse_archive_url",
]
