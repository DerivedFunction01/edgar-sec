"""Submissions endpoint and historical-file HTTP client for Pipeline A."""

from __future__ import annotations

from dataclasses import dataclass, field

from defs.sec_http import (
    HttpMetrics,
    PermanentHttpError,
    RateLimiter,
    ResponseTooLargeError,
    RetryExhausted,
    RetryPolicy,
    SecHttpClient,
)

SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
RETRYABLE_PERMANENT_KINDS = ("not_found", "forbidden", "bad_json")


@dataclass
class CikFetchResult:
    """Per-CIK fetch outcome including every historical file request."""

    cik_padded: str
    source_url: str = ""
    payload: dict | None = None
    byte_count: int = 0
    response_sha256: str = ""
    fetched_ok: bool = False
    permanent_error: str | None = None  # terminal, never retried further
    transient_error: str | None = None  # retry budget exhausted
    historical_payloads: list = field(default_factory=list)  # (url, name, payload)
    historical_errors: list[str] = field(default_factory=list)
    historical_files_fetched: int = 0

    def terminal_error(self) -> str | None:
        return self.permanent_error or self.transient_error


class SubmissionsClient:
    """Fetches the top-level submissions JSON and every historical file
    listed under ``filings.files``. Older JSON files are required inputs,
    not optional best effort; terminal failures are recorded per CIK."""

    def __init__(
        self,
        http: SecHttpClient | None = None,
        *,
        user_agent: str = "",
        rate_limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_s: float = 15.0,
        cache_dir: str = "",
        metrics: HttpMetrics | None = None,
        max_failure_attempts: int = 3,
        ignore_failure_history: bool = False,
    ):
        if http is None:
            if not user_agent:
                raise ValueError(
                    "user_agent is required to build the shared HTTP client"
                )
            http = SecHttpClient(
                user_agent=user_agent,
                rate_limiter=rate_limiter or RateLimiter(),
                retry_policy=retry_policy or RetryPolicy(),
                timeout_s=timeout_s,
                cache_dir=cache_dir or None,
                metrics=metrics or HttpMetrics(),
                max_failure_attempts=max_failure_attempts,
                ignore_failure_history=ignore_failure_history,
            )
        self.http = http

    def submissions_url(self, cik_padded: str) -> str:
        return f"{SUBMISSIONS_BASE}/CIK{cik_padded}.json"

    def fetch_cik(self, cik_padded: str) -> CikFetchResult:
        result = CikFetchResult(cik_padded=cik_padded)
        url = self.submissions_url(cik_padded)
        result.source_url = url
        try:
            payload, byte_count, sha256 = self.http.get_json_ex(url)
        except PermanentHttpError as exc:
            result.permanent_error = f"{exc.reason}"
            return result
        except ResponseTooLargeError as exc:
            result.permanent_error = f"{exc.reason}"
            return result
        except RetryExhausted as exc:
            result.transient_error = f"{exc.reason}"
            return result

        if not isinstance(payload, dict):
            result.permanent_error = "submissions payload is not a JSON object"
            return result

        result.payload = payload
        result.fetched_ok = True
        result.byte_count = byte_count
        result.response_sha256 = sha256

        filings = payload.get("filings") if isinstance(payload, dict) else None
        files = filings.get("files") if isinstance(filings, dict) else None
        if not isinstance(files, list):
            return result

        for descriptor in files:
            name = descriptor.get("name") if isinstance(descriptor, dict) else None
            if not name:
                result.historical_errors.append("filings.files entry without a name")
                continue
            file_url = f"{SUBMISSIONS_BASE}/{name}"
            try:
                hist_payload = self.http.get_json(file_url)
            except PermanentHttpError as exc:
                result.historical_errors.append(f"{name}: {exc.reason}")
                continue
            except RetryExhausted as exc:
                result.historical_errors.append(f"{name}: {exc.reason}")
                continue
            result.historical_payloads.append((file_url, name, hist_payload))
            result.historical_files_fetched += 1

        return result
