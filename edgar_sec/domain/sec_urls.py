"""Canonical SEC endpoint construction.

Two shapes are easy to get wrong and are normalized here: the CIK is zero-padded to
ten digits in a submissions URL but bare in an archive URL, and the archive URL's
accession is unhyphenated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from edgar_sec.domain.identity import AccessionNumber, Cik

SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
SEC_XBRL_API_BASE = "https://data.sec.gov/api/xbrl"
SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"
SEC_EDGAR_BASE = "https://www.sec.gov/Archives/edgar"
SEC_BROWSE_EDGAR_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
EFTS_SEARCH_BASE = "https://efts.sec.gov/LATEST/search-index"

STRUCTURED_FEED_FILES: dict[str, str] = {
    "usgaap": "usgaap.rss.xml",
    "risk_return": "xbrl-rr.rss.xml",
    "inline": "xbrl-inline.rss.xml",
    "all": "xbrlrss.all.xml",
}
SUBMISSIONS_BULK_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
)

CIK_PADDED_WIDTH = 10

# EDGAR generates this document in every interactive-data filing
# directory; its InputFiles section names the filing's XBRL members.
FILING_SUMMARY_DOCUMENT = "FilingSummary.xml"


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


def submissions_bulk_url() -> str:
    """Return the nightly bulk submissions ZIP URL (all CIK documents)."""
    return SUBMISSIONS_BULK_URL


def current_filings_url(
    form: str | None = None,
    cik: str | int | None = None,
    count: int | None = None,
    start: int | None = None,
) -> str:
    """Return the getcurrent Atom feed URL with only the supplied filters."""
    params: list[tuple[str, str]] = [("action", "getcurrent")]
    if form is not None:
        params.append(("type", str(form)))
    if cik is not None:
        params.append(("CIK", str(cik)))
    if count is not None:
        params.append(("count", str(count)))
    if start is not None:
        params.append(("start", str(start)))
    params.append(("output", "atom"))
    return f"{SEC_BROWSE_EDGAR_URL}?{urlencode(params)}"


def structured_feed_url(feed: str) -> str:
    """Return the URL of one named structured-disclosure live feed."""
    key = str(feed).strip()
    filename = STRUCTURED_FEED_FILES.get(key)
    if filename is None and key in STRUCTURED_FEED_FILES.values():
        filename = key
    if filename is None:
        raise ValueError(f"unknown structured-disclosure feed: {feed!r}")
    return f"{SEC_EDGAR_BASE}/{filename}"


def structured_archive_url(year: int, month: int) -> str:
    """Return the monthly structured-disclosure archive URL."""
    if not 1 <= int(month) <= 12:
        raise ValueError(f"month must be in 1..12, got {month!r}")
    return f"{SEC_EDGAR_BASE}/monthly/xbrlrss-{int(year):04d}-{int(month):02d}.xml"


def efts_search_url() -> str:
    """Return the EFTS search-index base URL; query encoding is the client's."""
    return EFTS_SEARCH_BASE


FULL_INDEX_FLAVOURS: tuple[str, ...] = (
    "master",
    "company",
    "form",
    "crawler",
    "xbrl",
)
DAILY_INDEX_FLAVOURS: tuple[str, ...] = ("master", "company", "form", "crawler")
_INDEX_EXTENSIONS: tuple[str, ...] = ("idx", "gz", "zip", "Z")


def _index_quarter(year: int, quarter: int) -> str:
    if not 1 <= int(quarter) <= 4:
        raise ValueError(f"quarter must be in 1..4, got {quarter!r}")
    return f"{int(year):04d}/QTR{int(quarter)}"


def full_index_url(
    year: int, quarter: int, flavour: str, extension: str = "idx"
) -> str:
    """Return one quarterly full-index file URL for a flavour.

    The crawler flavour is served only uncompressed; the other flavours
    are also served as ``gz`` / ``zip`` / ``Z`` archives of the same rows.
    """
    key = str(flavour).strip()
    if key not in FULL_INDEX_FLAVOURS:
        raise ValueError(f"unknown full-index flavour: {flavour!r}")
    if extension not in _INDEX_EXTENSIONS:
        raise ValueError(f"unknown index extension: {extension!r}")
    if key == "crawler" and extension != "idx":
        raise ValueError("the crawler index is served only as .idx")
    return (
        f"{SEC_EDGAR_BASE}/full-index/{_index_quarter(year, quarter)}/{key}.{extension}"
    )


def daily_index_url(day: date | str, flavour: str = "master") -> str:
    """Return one daily-index file URL; the quarter derives from ``day``.

    Daily files are per-day (``{flavour}.{YYYYMMDD}.idx``) and served only
    uncompressed, so the day is the builder's primary input.
    """
    key = str(flavour).strip()
    if key not in DAILY_INDEX_FLAVOURS:
        raise ValueError(f"unknown daily-index flavour: {flavour!r}")
    when = _coerce_index_day(day)
    quarter = (when.month - 1) // 3 + 1
    return (
        f"{SEC_EDGAR_BASE}/daily-index/{_index_quarter(when.year, quarter)}"
        f"/{key}.{when:%Y%m%d}.idx"
    )


def _coerce_index_day(day: date | str) -> date:
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    text = str(day).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"day must be a date or ISO/YYYYMMDD string, got {day!r}")


def companyconcept_url(cik: str | int, taxonomy: str, tag: str) -> str:
    """Return the companyconcept URL for one taxonomy tag of one CIK."""
    return (
        f"{SEC_XBRL_API_BASE}/companyconcept/CIK{normalize_cik(cik)}"
        f"/{taxonomy}/{tag}.json"
    )


def companyfacts_url(cik: str | int) -> str:
    """Return the companyfacts URL for one CIK's full facts document."""
    return f"{SEC_XBRL_API_BASE}/companyfacts/CIK{normalize_cik(cik)}.json"


def frames_url(taxonomy: str, tag: str, unit: str, period: str) -> str:
    """Return the frames URL for one concept aggregated over one period."""
    return f"{SEC_XBRL_API_BASE}/frames/{taxonomy}/{tag}/{unit}/{period}.json"


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


def index_json_url_for(
    accession: AccessionNumber | str,
    archive_cik: Cik | str | int,
    *,
    archive_base_url: str = SEC_ARCHIVE_BASE,
) -> str:
    """Build the directory ``index.json`` URL for an accession."""
    identity = AccessionNumber.from_any(accession)
    return archives_url(
        archive_cik,
        identity.normalized,
        "index.json",
        archive_base_url=archive_base_url,
    )


_ARCHIVE_PATH_RE = re.compile(
    r"^/Archives/edgar/data/(?P<archive_cik>\d+)/"
    r"(?P<accession>\d{10,18}?)/(?P<document_path>.+)$"
)

_SCHEME_RE = re.compile(r"[a-z][a-z0-9+.-]*")


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
        if any(_SCHEME_RE.fullmatch(item) is None for item in schemes):
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


def resolve_sec_href(base_url: str, reference: str) -> str:
    """Resolve an index reference while preserving unsafe path segments."""
    resolved = _resolve_reference_without_normalizing(base_url, reference)
    base = urlsplit(base_url)
    parts = urlsplit(resolved)
    if (
        parts.scheme.casefold() != "https"
        or parts.netloc.casefold() != "www.sec.gov"
        or (parts.scheme.casefold(), parts.netloc.casefold())
        != (base.scheme.casefold(), base.netloc.casefold())
        or parts.path.casefold() != "/ix"
        or parts.fragment
    ):
        return resolved
    try:
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return resolved
    documents = query.get("doc", ())
    if set(query) != {"doc"} or len(documents) != 1:
        return resolved
    origin = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
    unwrapped = _resolve_reference_without_normalizing(origin, documents[0])
    unwrapped_parts = urlsplit(unwrapped)
    if (unwrapped_parts.scheme.casefold(), unwrapped_parts.netloc.casefold()) != (
        parts.scheme.casefold(),
        parts.netloc.casefold(),
    ):
        return resolved
    return unwrapped


def resolve_archive_href(
    base_url: str,
    reference: str,
    accession: AccessionNumber | str,
    *,
    expected_archive_cik: Cik | str | int | None = None,
    policy: ArchiveUrlPolicy = DEFAULT_ARCHIVE_URL_POLICY,
) -> ArchiveUrlParts:
    """Resolve an href and validate it against its accession and optional CIK."""
    base = validate_archive_url(
        base_url,
        accession,
        expected_archive_cik=expected_archive_cik,
        policy=policy,
    )
    resolved = resolve_sec_href(base.url, reference)
    source = urlsplit(base.url)
    target = urlsplit(resolved)
    if (source.scheme.casefold(), source.netloc.casefold()) != (
        target.scheme.casefold(),
        target.netloc.casefold(),
    ):
        raise ValueError("archive href is outside the base origin")
    return validate_archive_url(
        resolved,
        accession,
        expected_archive_cik=expected_archive_cik,
        policy=policy,
    )


def _resolve_reference_without_normalizing(base_url: str, reference: str) -> str:
    base = urlsplit(base_url)
    href = urlsplit(reference)
    if href.scheme:
        return reference
    if href.netloc:
        return f"{base.scheme}:{reference}"
    if href.path.startswith("/"):
        path = href.path
    elif href.path:
        path = f"{base.path.rsplit('/', 1)[0]}/{href.path}"
    else:
        path = base.path
    query = href.query if "?" in reference else (base.query if not href.path else "")
    fragment = href.fragment
    return urlunsplit((base.scheme, base.netloc, path, query, fragment))


def full_submission_url_for(archive_cik: str, accession: str) -> str:
    """Build the complete SGML submission ``.txt`` bundle URL for an accession.

    Example: ``.../data/320193/000032019320000096/0000320193-20-000096.txt``
    """
    canonical = normalize_accession(accession)
    if canonical is None:
        raise ValueError(f"accession must be canonicalizable: {accession!r}")
    dashed = accession_hyphenated(canonical)
    return archives_url(int(archive_cik), canonical, f"{dashed}.txt")


def xbrl_package_url_for(archive_cik: str, accession: str) -> str:
    """Build the EDGAR-generated XBRL package ``-xbrl.zip`` URL for an accession.

    Example: ``.../data/320193/000032019320000096/0000320193-20-000096-xbrl.zip``
    """
    canonical = normalize_accession(accession)
    if canonical is None:
        raise ValueError(f"accession must be canonicalizable: {accession!r}")
    dashed = accession_hyphenated(canonical)
    return archives_url(int(archive_cik), canonical, f"{dashed}-xbrl.zip")


# Surface ids: the governed census of SEC surfaces, classified by URL shape.
# The freshness policy for each id lives in the SEC settings provider.
SURFACE_SUBMISSIONS = "submissions"
SURFACE_SUBMISSIONS_HISTORICAL_SHARDS = "submissions_historical_shards"
SURFACE_SUBMISSIONS_BULK = "submissions_bulk"
SURFACE_COMPANYCONCEPT = "companyconcept"
SURFACE_COMPANYFACTS = "companyfacts"
SURFACE_FRAMES = "frames"
SURFACE_ARCHIVE_DOCUMENTS = "archive_documents"
SURFACE_ARCHIVE_INDEX_PAGES = "archive_index_pages"
SURFACE_ARCHIVE_INDEX_JSON = "archive_index_json"
SURFACE_FULL_SUBMISSION_BUNDLES = "full_submission_bundles"
SURFACE_XBRL_PACKAGES = "xbrl_packages"
SURFACE_TAXONOMY_ARCHIVES = "taxonomy_archives"
SURFACE_COMPANY_TICKERS = "company_tickers"
SURFACE_COMPANY_TICKERS_EXCHANGE = "company_tickers_exchange"
SURFACE_COMPANY_TICKERS_MF = "company_tickers_mf"
SURFACE_TICKER_TXT = "ticker_txt"
SURFACE_CIK_LOOKUP = "cik_lookup"
SURFACE_FULL_INDEX = "full_index"
SURFACE_DAILY_INDEX = "daily_index"
SURFACE_CURRENT_FILINGS = "current_filings"
SURFACE_STRUCTURED_DISCLOSURE_FEEDS = "structured_disclosure_feeds"
SURFACE_STRUCTURED_DISCLOSURE_ARCHIVES = "structured_disclosure_archives"
SURFACE_EFTS = "efts"

SEC_SURFACES: tuple[str, ...] = (
    SURFACE_SUBMISSIONS,
    SURFACE_SUBMISSIONS_HISTORICAL_SHARDS,
    SURFACE_SUBMISSIONS_BULK,
    SURFACE_COMPANYCONCEPT,
    SURFACE_COMPANYFACTS,
    SURFACE_FRAMES,
    SURFACE_ARCHIVE_DOCUMENTS,
    SURFACE_ARCHIVE_INDEX_PAGES,
    SURFACE_ARCHIVE_INDEX_JSON,
    SURFACE_FULL_SUBMISSION_BUNDLES,
    SURFACE_XBRL_PACKAGES,
    SURFACE_TAXONOMY_ARCHIVES,
    SURFACE_COMPANY_TICKERS,
    SURFACE_COMPANY_TICKERS_EXCHANGE,
    SURFACE_COMPANY_TICKERS_MF,
    SURFACE_TICKER_TXT,
    SURFACE_CIK_LOOKUP,
    SURFACE_FULL_INDEX,
    SURFACE_DAILY_INDEX,
    SURFACE_CURRENT_FILINGS,
    SURFACE_STRUCTURED_DISCLOSURE_FEEDS,
    SURFACE_STRUCTURED_DISCLOSURE_ARCHIVES,
    SURFACE_EFTS,
)

# Each builder names the surface its URLs belong to.
URL_BUILDER_SURFACES: dict[str, str] = {
    "submissions_url": SURFACE_SUBMISSIONS,
    "historical_submissions_url": SURFACE_SUBMISSIONS_HISTORICAL_SHARDS,
    "submissions_bulk_url": SURFACE_SUBMISSIONS_BULK,
    "companyconcept_url": SURFACE_COMPANYCONCEPT,
    "companyfacts_url": SURFACE_COMPANYFACTS,
    "frames_url": SURFACE_FRAMES,
    "archives_url": SURFACE_ARCHIVE_DOCUMENTS,
    "index_url_for": SURFACE_ARCHIVE_INDEX_PAGES,
    "index_json_url_for": SURFACE_ARCHIVE_INDEX_JSON,
    "full_submission_url_for": SURFACE_FULL_SUBMISSION_BUNDLES,
    "xbrl_package_url_for": SURFACE_XBRL_PACKAGES,
    "full_index_url": SURFACE_FULL_INDEX,
    "daily_index_url": SURFACE_DAILY_INDEX,
    "current_filings_url": SURFACE_CURRENT_FILINGS,
    "structured_feed_url": SURFACE_STRUCTURED_DISCLOSURE_FEEDS,
    "structured_archive_url": SURFACE_STRUCTURED_DISCLOSURE_ARCHIVES,
    "efts_search_url": SURFACE_EFTS,
}

# Classification rules as data: (surface id, host, path pattern), first match
# wins. The sec-surface scanner reads this same table statically, so runtime
# classification and the gate cannot drift apart.
SEC_SURFACE_RULES: tuple[tuple[str, str, str], ...] = (
    (
        SURFACE_SUBMISSIONS_HISTORICAL_SHARDS,
        "data.sec.gov",
        r"^/submissions/[^/]*-submissions-[^/]*\.json$",
    ),
    (SURFACE_SUBMISSIONS, "data.sec.gov", r"^/submissions(/|$)"),
    (SURFACE_COMPANYCONCEPT, "data.sec.gov", r"^/api/xbrl/companyconcept(/|$)"),
    (SURFACE_COMPANYFACTS, "data.sec.gov", r"^/api/xbrl/companyfacts(/|$)"),
    (SURFACE_FRAMES, "data.sec.gov", r"^/api/xbrl/frames(/|$)"),
    (SURFACE_CURRENT_FILINGS, "www.sec.gov", r"^/cgi-bin/browse-edgar"),
    (SURFACE_EFTS, "efts.sec.gov", r"^/LATEST/search-index$"),
    (
        SURFACE_STRUCTURED_DISCLOSURE_ARCHIVES,
        "www.sec.gov",
        r"^/Archives/edgar/monthly/xbrlrss-\d{4}-\d{2}\.xml$",
    ),
    (
        SURFACE_STRUCTURED_DISCLOSURE_FEEDS,
        "www.sec.gov",
        r"^/Archives/edgar/(usgaap\.rss|xbrl-rr\.rss|xbrl-inline\.rss"
        r"|xbrlrss\.all)\.xml$",
    ),
    (
        SURFACE_SUBMISSIONS_BULK,
        "www.sec.gov",
        r"^/Archives/edgar/daily-index/bulkdata/submissions\.zip$",
    ),
    (
        SURFACE_FULL_INDEX,
        "www.sec.gov",
        r"^/Archives/edgar/full-index/\d{4}/QTR[1-4]/[^/]+$",
    ),
    (
        SURFACE_DAILY_INDEX,
        "www.sec.gov",
        r"^/Archives/edgar/daily-index/\d{4}/QTR[1-4]/[^/]+$",
    ),
    (
        SURFACE_CIK_LOOKUP,
        "www.sec.gov",
        r"^/Archives/edgar/cik-lookup-data\.txt$",
    ),
    (SURFACE_COMPANY_TICKERS, "www.sec.gov", r"^/files/company_tickers\.json$"),
    (
        SURFACE_COMPANY_TICKERS_EXCHANGE,
        "www.sec.gov",
        r"^/files/company_tickers_exchange\.json$",
    ),
    (
        SURFACE_COMPANY_TICKERS_MF,
        "www.sec.gov",
        r"^/files/company_tickers_mf\.json$",
    ),
    (SURFACE_TICKER_TXT, "www.sec.gov", r"^/include/ticker\.txt$"),
    (SURFACE_TAXONOMY_ARCHIVES, "www.sec.gov", r"^/files/[^/]*\.zip$"),
    (
        SURFACE_ARCHIVE_INDEX_JSON,
        "www.sec.gov",
        r"^/Archives/edgar/data/\d+/[^/]+/index\.json$",
    ),
    (
        SURFACE_ARCHIVE_INDEX_PAGES,
        "www.sec.gov",
        r"^/Archives/edgar/data/\d+/[^/]+/[^/]*-index(-headers)?\.(html|txt)$",
    ),
    (
        SURFACE_FULL_SUBMISSION_BUNDLES,
        "www.sec.gov",
        r"^/Archives/edgar/data/\d+/[^/]+/\d{10}-\d{2}-\d{6}\.txt$",
    ),
    (
        SURFACE_XBRL_PACKAGES,
        "www.sec.gov",
        r"^/Archives/edgar/data/\d+/[^/]+/[^/]*-xbrl\.zip$",
    ),
    (SURFACE_ARCHIVE_DOCUMENTS, "www.sec.gov", r"^/Archives/edgar/data(/|$)"),
    (SURFACE_TAXONOMY_ARCHIVES, "xbrl.sec.gov", r"^"),
)

_COMPILED_SURFACE_RULES = tuple(
    (surface_id, host, re.compile(pattern))
    for surface_id, host, pattern in SEC_SURFACE_RULES
)


def classify_sec_surface(url: str | None) -> str | None:
    """Classify a SEC URL into its governed surface id, or None.

    Classification is by URL shape (host and path), never by file suffix:
    a transient ``.txt`` and a static ``index.json`` classify correctly.
    """
    if not url:
        return None
    parts = urlsplit(str(url).strip())
    host = (parts.hostname or "").casefold()
    path = parts.path or ""
    for surface_id, rule_host, pattern in _COMPILED_SURFACE_RULES:
        if host == rule_host and pattern.search(path):
            return surface_id
    return None


__all__ = [
    "CIK_PADDED_WIDTH",
    "EFTS_SEARCH_BASE",
    "SEC_ARCHIVE_BASE",
    "SEC_BROWSE_EDGAR_URL",
    "SEC_EDGAR_BASE",
    "SEC_SUBMISSIONS_BASE",
    "SEC_XBRL_API_BASE",
    "DAILY_INDEX_FLAVOURS",
    "FULL_INDEX_FLAVOURS",
    "STRUCTURED_FEED_FILES",
    "SUBMISSIONS_BULK_URL",
    "DEFAULT_ARCHIVE_URL_POLICY",
    "FILING_SUMMARY_DOCUMENT",
    "SEC_SURFACES",
    "SEC_SURFACE_RULES",
    "SURFACE_ARCHIVE_DOCUMENTS",
    "SURFACE_ARCHIVE_INDEX_JSON",
    "SURFACE_ARCHIVE_INDEX_PAGES",
    "SURFACE_CIK_LOOKUP",
    "SURFACE_COMPANYCONCEPT",
    "SURFACE_COMPANYFACTS",
    "SURFACE_FRAMES",
    "SURFACE_DAILY_INDEX",
    "SURFACE_FULL_INDEX",
    "SURFACE_CURRENT_FILINGS",
    "SURFACE_EFTS",
    "SURFACE_STRUCTURED_DISCLOSURE_ARCHIVES",
    "SURFACE_STRUCTURED_DISCLOSURE_FEEDS",
    "SURFACE_COMPANY_TICKERS",
    "SURFACE_COMPANY_TICKERS_EXCHANGE",
    "SURFACE_COMPANY_TICKERS_MF",
    "SURFACE_FULL_SUBMISSION_BUNDLES",
    "SURFACE_SUBMISSIONS",
    "SURFACE_SUBMISSIONS_BULK",
    "SURFACE_SUBMISSIONS_HISTORICAL_SHARDS",
    "SURFACE_TAXONOMY_ARCHIVES",
    "SURFACE_TICKER_TXT",
    "SURFACE_XBRL_PACKAGES",
    "URL_BUILDER_SURFACES",
    "ArchiveUrlPolicy",
    "ArchiveUrlParts",
    "accession_hyphenated",
    "archives_url",
    "classify_sec_surface",
    "companyconcept_url",
    "companyfacts_url",
    "frames_url",
    "current_filings_url",
    "daily_index_url",
    "full_index_url",
    "efts_search_url",
    "full_submission_url_for",
    "historical_submissions_url",
    "index_json_url_for",
    "index_url_for",
    "normalize_accession",
    "normalize_cik",
    "parse_archive_url",
    "resolve_archive_href",
    "resolve_sec_href",
    "structured_archive_url",
    "structured_feed_url",
    "submissions_bulk_url",
    "submissions_url",
    "validate_archive_url",
    "xbrl_package_url_for",
]
