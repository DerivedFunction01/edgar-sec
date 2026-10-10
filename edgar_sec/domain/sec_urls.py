"""Canonical SEC endpoint construction.

Two shapes are easy to get wrong and are normalized here: the CIK is zero-padded to
ten digits in a submissions URL but bare in an archive URL, and the archive URL's
accession is unhyphenated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from edgar_sec.domain.identity import AccessionNumber, Cik

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


def archives_url(
    cik: str | int,
    accession_number: str,
    document_name: str,
    *,
    archive_base_url: str = SEC_ARCHIVE_BASE,
) -> str:
    """Return the canonical EDGAR archive document URL.

    Inputs are assumed usable and a nonsense URL is built rather than refused;
    tolerating a missing or malformed document belongs in the engine.
    """
    accession_clean = str(accession_number).replace("-", "")
    return (
        f"{archive_base_url.rstrip('/')}/{int(cik)}/{accession_clean}/{document_name}"
    )


def index_url_for(
    accession: AccessionNumber | str,
    archive_cik: Cik | str | int,
    *,
    archive_base_url: str = SEC_ARCHIVE_BASE,
) -> str:
    """Build an index URL using the caller's archive-directory CIK."""
    identity = AccessionNumber.from_any(accession)
    return archives_url(
        archive_cik,
        identity.normalized,
        f"{identity}-index.html",
        archive_base_url=archive_base_url,
    )


_ARCHIVE_PATH_RE = re.compile(
    r"^/Archives/edgar/data/(?P<archive_cik>\d+)/"
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


@dataclass(frozen=True, slots=True)
class ArchiveUrlPolicy:
    allowed_schemes: frozenset[str] = frozenset({"https"})
    allowed_hosts: frozenset[str] = frozenset({"www.sec.gov"})

    def __post_init__(self) -> None:
        schemes = frozenset(item.casefold() for item in self.allowed_schemes)
        hosts = frozenset(item.casefold() for item in self.allowed_hosts)
        if not schemes or not hosts or any(not item for item in (*schemes, *hosts)):
            raise ValueError("archive URL policy needs schemes and hosts")
        if any(not re.fullmatch(r"[a-z][a-z0-9+.-]*", item) for item in schemes):
            raise ValueError("archive URL policy contains an invalid scheme")
        if any("/" in item or ":" in item or "@" in item for item in hosts):
            raise ValueError("archive URL policy contains an invalid host")
        object.__setattr__(self, "allowed_schemes", schemes)
        object.__setattr__(self, "allowed_hosts", hosts)


DEFAULT_ARCHIVE_URL_POLICY = ArchiveUrlPolicy()


def _archive_parts(path: str, url: str) -> ArchiveUrlParts | None:
    match = _ARCHIVE_PATH_RE.fullmatch(path)
    if match is None:
        return None
    accession = normalize_accession(match.group("accession"))
    document_path = match.group("document_path")
    if accession is None or not document_path.strip("/"):
        return None
    return ArchiveUrlParts(
        url=url,
        archive_cik=match.group("archive_cik"),
        accession=accession,
        document_path=document_path,
    )


def parse_archive_url(url: str | None) -> ArchiveUrlParts | None:
    """Parse an archive document URL, or return None when it is not one.

    Returns None for other hosts, missing segments, and an empty document path.
    """
    if not url:
        return None
    value = str(url).strip()
    prefix = f"{SEC_ARCHIVE_BASE}/"
    if not value.startswith(prefix):
        return None
    parts = _archive_parts(value[len("https://www.sec.gov") :], value)
    if parts is None:
        return None
    return parts


def validate_archive_url(
    url: str,
    accession: AccessionNumber | str,
    *,
    expected_archive_cik: Cik | str | int | None = None,
    policy: ArchiveUrlPolicy = DEFAULT_ARCHIVE_URL_POLICY,
) -> ArchiveUrlParts:
    """Validate archive path safety and accession identity, with optional CIK scope."""
    if not isinstance(url, str) or not url or url != url.strip():
        raise ValueError("archive URL must be a trimmed non-empty string")
    if (
        "?" in url
        or "#" in url
        or any(ord(char) <= 32 or ord(char) == 127 for char in url)
    ):
        raise ValueError("archive URL contains a query, fragment, or control character")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise ValueError("archive URL is malformed") from error
    host = parts.hostname
    if (
        parts.scheme.casefold() not in policy.allowed_schemes
        or host is None
        or host.casefold() not in policy.allowed_hosts
        or parts.username is not None
        or parts.password is not None
        or port is not None
    ):
        raise ValueError("archive URL host or scheme is not allowed")
    path = parts.path
    segments = path.split("/")
    if (
        "%" in path
        or "\\" in path
        or "//" in path
        or any(segment in {".", ".."} for segment in segments)
    ):
        raise ValueError("archive URL path contains an unsafe segment")
    archive = _archive_parts(path, url)
    try:
        expected = AccessionNumber.from_any(accession).normalized
    except (TypeError, ValueError) as error:
        raise ValueError("expected accession is invalid") from error
    if archive is None or archive.accession != expected:
        raise ValueError("archive URL is outside the expected accession")
    if expected_archive_cik is not None:
        try:
            expected_cik = int(Cik.from_raw(expected_archive_cik))
        except (TypeError, ValueError) as error:
            raise ValueError("expected archive CIK is invalid") from error
        if int(archive.archive_cik) != expected_cik:
            raise ValueError("archive URL has the wrong archive CIK")
    return archive


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
    "DEFAULT_ARCHIVE_URL_POLICY",
    "ArchiveUrlPolicy",
    "ArchiveUrlParts",
    "accession_hyphenated",
    "archives_url",
    "full_submission_url_for",
    "historical_submissions_url",
    "index_url_for",
    "normalize_accession",
    "normalize_cik",
    "parse_archive_url",
    "submissions_url",
    "validate_archive_url",
]
