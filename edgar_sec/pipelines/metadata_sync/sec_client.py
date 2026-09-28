"""Submissions endpoint and historical-file client for the metadata pipeline.

The client owns the fan-out from one CIK to its main submissions document plus
every historical file listed under ``filings.files``. Historical files are
required inputs rather than best-effort extras, so terminal per-file failures
are recorded on the result instead of raised, letting the engine decide
``partial`` versus ``failed`` status.

The HTTP client is injected, which lets tests substitute a scripted session
while pacing, retry, cache, and failure-ledger behavior stay under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edgar_sec.domain.sec_urls import historical_submissions_url, submissions_url
from edgar_sec.foundation.runtime.settings.sec import SecSettings
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import PermanentHttpError, RetryExhausted

__all__ = ["CikFetchResult", "SubmissionsClient"]


@dataclass
class CikFetchResult:
    """Per-CIK fetch outcome covering the document and all historical files."""

    cik_padded: str
    source_url: str = ""
    payload: dict | None = None
    byte_count: int = 0
    response_sha256: str = ""
    fetched_ok: bool = False
    permanent_error: str | None = None
    transient_error: str | None = None
    historical_payloads: list = field(default_factory=list)
    historical_errors: list[str] = field(default_factory=list)
    historical_files_fetched: int = 0

    def terminal_error(self) -> str | None:
        """Permanent failure if present, else the exhausted-retry failure."""
        return self.permanent_error or self.transient_error


class SubmissionsClient:
    """Fetches one CIK's submissions JSON and every historical file it lists."""

    def __init__(
        self,
        http: SecHttpClient | None = None,
        *,
        user_agent: str = "",
        settings: SecSettings | None = None,
        cache_dir: str | None = None,
    ) -> None:
        if http is not None:
            self.http = http
            return
        if settings is not None:
            self.http = SecHttpClient.from_settings(settings, cache_dir=cache_dir)
            return
        if not user_agent:
            raise ValueError(
                "user_agent or settings is required to build the SEC HTTP client"
            )
        self.http = SecHttpClient(user_agent=user_agent, cache_dir=cache_dir)

    def fetch_cik(self, cik_padded: str) -> CikFetchResult:
        """Fetch the submissions document and all of its historical files."""
        result = CikFetchResult(cik_padded=cik_padded)
        url = submissions_url(cik_padded)
        result.source_url = url

        try:
            payload, byte_count, sha256 = self.http.get_json_ex(url)
        except PermanentHttpError as exc:
            result.permanent_error = str(exc.reason)
            return result
        except RetryExhausted as exc:
            result.transient_error = str(exc.reason)
            return result

        if not isinstance(payload, dict):
            result.permanent_error = "submissions payload is not a JSON object"
            return result

        result.payload = payload
        result.fetched_ok = True
        result.byte_count = byte_count
        result.response_sha256 = sha256

        for name in self._historical_names(payload):
            file_url = historical_submissions_url(name)
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

    @staticmethod
    def _historical_names(payload: dict[str, Any]) -> list[str]:
        filings = payload.get("filings")
        files = filings.get("files") if isinstance(filings, dict) else None
        if not isinstance(files, list):
            return []
        names: list[str] = []
        for descriptor in files:
            name = descriptor.get("name") if isinstance(descriptor, dict) else None
            if name:
                names.append(str(name))
        return names
