"""SEC identity, rate limit, timeout, retry, and failure history settings.

Contact identity is secret-like: resolved from the environment or explicit CLI options,
but never rendered into generated dotenv output, persisted, or logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import SettingSpec

DEFAULT_USER_AGENT = "Sample Company Name AdminContact@sample.com"
DEFAULT_RATE_LIMIT_RPS = 8.0
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_FAILURE_ATTEMPTS = 3
DEFAULT_BULK_ARCHIVE_RETENTION = 2
DEFAULT_BULK_ARCHIVE_MAX_BYTES = 8 * 1024**3
DEFAULT_TRANSIENT_TTL_S = 24 * 60 * 60
DEFAULT_FEED_MAX_PAGES = 100

SURFACE_KIND_STATIC = "static"
SURFACE_KIND_TRANSIENT = "transient"
SURFACE_KIND_NO_STORE = "no-store"
DEFAULT_STRUCTURED_FEED_TTL_S = 300


def _require_positive(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"expected a positive integer, got {value!r}")


@dataclass(frozen=True, slots=True)
class SurfacePolicy:
    """Freshness policy for one governed SEC surface.

    ``ttl_path`` names the settings path carrying the surface's TTL; a
    transient surface without one inherits ``sec.ttl.default_s``.
    """

    surface_id: str
    kind: str
    cadence: str
    ttl_path: str | None = None


# The governed census, keyed by the surface ids the domain URL classifier
# produces. Static surfaces never expire; transient surfaces carry a TTL.
SURFACE_POLICIES: dict[str, SurfacePolicy] = {
    policy.surface_id: policy
    for policy in (
        SurfacePolicy(
            "submissions",
            SURFACE_KIND_TRANSIENT,
            "filing events",
            "sec.ttl.submissions",
        ),
        SurfacePolicy(
            "submissions_bulk",
            SURFACE_KIND_TRANSIENT,
            "nightly rebuild (~03:00 ET)",
            "sec.ttl.submissions_bulk",
        ),
        SurfacePolicy(
            "companyfacts_bulk",
            SURFACE_KIND_TRANSIENT,
            "nightly rebuild; the TTL classifies only — the payload streams "
            "to the bulk store and never enters the response cache",
            "sec.ttl.companyfacts_bulk",
        ),
        SurfacePolicy(
            "companyfacts",
            SURFACE_KIND_TRANSIENT,
            "filing events",
            "sec.ttl.companyfacts",
        ),
        SurfacePolicy(
            "frames",
            SURFACE_KIND_TRANSIENT,
            "filing events",
            "sec.ttl.frames",
        ),
        SurfacePolicy(
            "companyconcept",
            SURFACE_KIND_TRANSIENT,
            "filing events",
            "sec.ttl.companyconcept",
        ),
        SurfacePolicy(
            "company_tickers",
            SURFACE_KIND_TRANSIENT,
            "daily refresh",
            "sec.ttl.company_tickers",
        ),
        SurfacePolicy(
            "company_tickers_exchange",
            SURFACE_KIND_TRANSIENT,
            "daily refresh",
            "sec.ttl.company_tickers_exchange",
        ),
        SurfacePolicy(
            "company_tickers_mf",
            SURFACE_KIND_TRANSIENT,
            "daily refresh",
            "sec.ttl.company_tickers_mf",
        ),
        SurfacePolicy(
            "ticker_txt", SURFACE_KIND_TRANSIENT, "daily refresh", "sec.ttl.ticker_txt"
        ),
        SurfacePolicy(
            "cik_lookup", SURFACE_KIND_TRANSIENT, "daily refresh", "sec.ttl.cik_lookup"
        ),
        SurfacePolicy("archive_documents", SURFACE_KIND_STATIC, "immutable once filed"),
        SurfacePolicy(
            "archive_index_pages", SURFACE_KIND_STATIC, "immutable once filed"
        ),
        SurfacePolicy(
            "archive_index_json", SURFACE_KIND_STATIC, "immutable once filed"
        ),
        SurfacePolicy(
            "full_submission_bundles", SURFACE_KIND_STATIC, "immutable once filed"
        ),
        SurfacePolicy("xbrl_packages", SURFACE_KIND_STATIC, "immutable once filed"),
        SurfacePolicy(
            "submissions_historical_shards",
            SURFACE_KIND_STATIC,
            "immutable once rolled",
        ),
        SurfacePolicy(
            "taxonomy_archives", SURFACE_KIND_STATIC, "immutable per release"
        ),
        SurfacePolicy("current_filings", SURFACE_KIND_NO_STORE, "filing events"),
        SurfacePolicy(
            "browse_edgar",
            SURFACE_KIND_TRANSIENT,
            "daily refresh",
            "sec.ttl.browse_edgar",
        ),
        SurfacePolicy(
            "structured_disclosure_feeds",
            SURFACE_KIND_TRANSIENT,
            "10-minute publication cycle",
            "sec.ttl.structured_disclosure_feeds",
        ),
        SurfacePolicy(
            "structured_disclosure_archives",
            SURFACE_KIND_STATIC,
            "immutable once the month completes",
        ),
        SurfacePolicy(
            "feed_archives",
            SURFACE_KIND_STATIC,
            "dated tarballs are immutable once published",
        ),
        SurfacePolicy("efts", SURFACE_KIND_NO_STORE, "live index"),
        SurfacePolicy(
            "full_index",
            SURFACE_KIND_TRANSIENT,
            "quarterly publication; immutable once the quarter completes",
            "sec.ttl.full_index",
        ),
        SurfacePolicy(
            "daily_index",
            SURFACE_KIND_TRANSIENT,
            "daily refresh",
            "sec.ttl.daily_index",
        ),
        SurfacePolicy(
            "bdc_datasets",
            SURFACE_KIND_STATIC,
            "static per vintage; a re-posted vintage is a new content hash",
        ),
        SurfacePolicy(
            "nmfp_datasets",
            SURFACE_KIND_STATIC,
            "static per vintage; a re-posted vintage is a new content hash",
        ),
        SurfacePolicy(
            "mfrr_datasets",
            SURFACE_KIND_STATIC,
            "static per vintage; a re-posted vintage is a new content hash",
        ),
        SurfacePolicy(
            "fsds_datasets",
            SURFACE_KIND_STATIC,
            "static per vintage; a re-posted vintage is a new content hash",
        ),
        SurfacePolicy(
            "bdc_report",
            SURFACE_KIND_STATIC,
            "static per report year; a re-published year is a new content hash",
        ),
    )
}


@dataclass(frozen=True, slots=True)
class SecSettings:
    """Convenience typed view of SEC transport and identity settings."""

    user_agent: str = DEFAULT_USER_AGENT
    rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES
    max_failure_attempts: int = DEFAULT_MAX_FAILURE_ATTEMPTS
    bulk_archive_retention: int = DEFAULT_BULK_ARCHIVE_RETENTION
    bulk_archive_max_bytes: int = DEFAULT_BULK_ARCHIVE_MAX_BYTES

    @property
    def header_user_agent(self) -> str:
        """Formatted SEC user-agent header string."""
        return self.user_agent.strip()


def get_sec_specs() -> dict[str, dict[str, SettingSpec]]:
    from . import SettingSpec

    return {
        "sec": {
            "user_agent": SettingSpec(
                value_type=str,
                default=DEFAULT_USER_AGENT,
                env=True,
                cli=True,
                secret=True,
                description=(
                    "SEC contact identity required for live fetches, formatted as "
                    "'AppName/1.0 your-email@example.com'"
                ),
            ),
            "rate_limit_rps": SettingSpec(
                value_type=float,
                default=DEFAULT_RATE_LIMIT_RPS,
                env=True,
                cli=True,
                machine_local=True,
                description="aggregate SEC request rate limit across workers (requests/sec)",
            ),
            "timeout_s": SettingSpec(
                value_type=float,
                default=DEFAULT_TIMEOUT_S,
                env=True,
                cli=True,
                machine_local=True,
                description="HTTP request timeout in seconds",
            ),
            "max_retries": SettingSpec(
                value_type=int,
                default=DEFAULT_MAX_RETRIES,
                env=True,
                cli=True,
                machine_local=True,
                description="maximum retry attempts for transient SEC HTTP failures",
            ),
            "max_failure_attempts": SettingSpec(
                value_type=int,
                default=DEFAULT_MAX_FAILURE_ATTEMPTS,
                env=True,
                cli=True,
                machine_local=True,
                description="failure ledger budget before a repeatedly failing URL is skipped",
            ),
            "bulk_archive": {
                "retention": SettingSpec(
                    value_type=int,
                    default=DEFAULT_BULK_ARCHIVE_RETENTION,
                    env=True,
                    cli=True,
                    machine_local=True,
                    validate=_require_positive,
                    description=(
                        "newest bulk archives kept per source in the bulk-archive "
                        "store; older archives are pruned at put time"
                    ),
                ),
                "max_bytes": SettingSpec(
                    value_type=int,
                    default=DEFAULT_BULK_ARCHIVE_MAX_BYTES,
                    env=True,
                    cli=True,
                    machine_local=True,
                    validate=_require_positive,
                    description="byte bound for one streamed bulk archive download",
                ),
            },
            "feeds": {
                "max_pages": SettingSpec(
                    value_type=int,
                    default=DEFAULT_FEED_MAX_PAGES,
                    env=True,
                    cli=True,
                    machine_local=True,
                    validate=_require_positive,
                    description=(
                        "page cap for one current-filings feed walk; a walk that "
                        "reaches it stops rather than paging without bound"
                    ),
                ),
            },
            "ttl": _ttl_specs(),
        },
    }


def _ttl_spec(description: str, default: int = DEFAULT_TRANSIENT_TTL_S) -> SettingSpec:
    from . import SettingSpec

    return SettingSpec(
        value_type=int,
        default=default,
        env=True,
        cli=True,
        machine_local=True,
        validate=_require_positive,
        description=description,
    )


def _ttl_specs() -> dict[str, SettingSpec]:
    return {
        "default_s": _ttl_spec(
            "freshness window inherited by a transient SEC surface with no "
            "surface-specific TTL setting"
        ),
        "submissions": _ttl_spec("freshness window for per-CIK submissions JSON"),
        "submissions_bulk": _ttl_spec(
            "freshness window for the submissions bulk archive"
        ),
        "companyfacts_bulk": _ttl_spec(
            "freshness window for the companyfacts bulk archive"
        ),
        "companyconcept": _ttl_spec("freshness window for companyconcept JSON"),
        "companyfacts": _ttl_spec("freshness window for companyfacts JSON"),
        "frames": _ttl_spec("freshness window for frames JSON"),
        "company_tickers": _ttl_spec("freshness window for company_tickers.json"),
        "company_tickers_exchange": _ttl_spec(
            "freshness window for company_tickers_exchange.json"
        ),
        "company_tickers_mf": _ttl_spec("freshness window for company_tickers_mf.json"),
        "ticker_txt": _ttl_spec("freshness window for ticker.txt"),
        "cik_lookup": _ttl_spec("freshness window for cik-lookup-data.txt"),
        "full_index": _ttl_spec(
            "freshness window for the in-progress quarter's full index; "
            "completed quarters are immutable once published"
        ),
        "daily_index": _ttl_spec("freshness window for daily index files"),
        "browse_edgar": _ttl_spec(
            "freshness window for browse-edgar company and series pages"
        ),
        "structured_disclosure_feeds": _ttl_spec(
            "freshness window for structured-disclosure feeds; strictly below "
            "the 600-second publication cycle",
            default=DEFAULT_STRUCTURED_FEED_TTL_S,
        ),
    }


__all__ = [
    "DEFAULT_BULK_ARCHIVE_MAX_BYTES",
    "DEFAULT_BULK_ARCHIVE_RETENTION",
    "DEFAULT_FEED_MAX_PAGES",
    "DEFAULT_MAX_FAILURE_ATTEMPTS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RATE_LIMIT_RPS",
    "DEFAULT_STRUCTURED_FEED_TTL_S",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_TRANSIENT_TTL_S",
    "DEFAULT_USER_AGENT",
    "SURFACE_KIND_NO_STORE",
    "SURFACE_KIND_STATIC",
    "SURFACE_KIND_TRANSIENT",
    "SURFACE_POLICIES",
    "SecSettings",
    "SurfacePolicy",
    "get_sec_specs",
]
