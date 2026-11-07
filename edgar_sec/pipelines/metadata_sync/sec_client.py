"""Submissions endpoint and historical-file client for the metadata pipeline.
Historical files are required inputs, so a terminal per-file failure is recorded
on the result rather than raised, leaving ``partial`` versus ``failed`` to the
engine. The HTTP client is injected.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from edgar_sec.domain.sec_urls import (
    SUBMISSIONS_BULK_URL,
    historical_submissions_url,
    submissions_bulk_url,
    submissions_url,
)
from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.runtime.settings.paths import DEFAULT_CACHE_TTL_S
from edgar_sec.foundation.runtime.settings.sec import SecSettings
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import PermanentHttpError, RetryExhausted
from edgar_sec.infra.sec_http.streaming import StreamFailure
from edgar_sec.infra.storage.bulk_archive import ArchiveReference, BulkArchiveStore
from edgar_sec.infra.storage.member_index import MemberIndex, ensure_member_index

__all__ = [
    "SUBMISSIONS_BULK_SOURCE_ID",
    "BulkSubmissionsArchive",
    "BulkSubmissionsClient",
    "CikFetchResult",
    "SubmissionsClient",
]

SUBMISSIONS_BULK_SOURCE_ID = "submissions_bulk"


def _validate_bulk_redirect(url: str) -> None:
    """Bulk downloads may redirect only within the bulkdata directory."""
    parts = urlsplit(url)
    expected = urlsplit(SUBMISSIONS_BULK_URL)
    if (
        parts.scheme != "https"
        or parts.netloc != expected.netloc
        or not parts.path.startswith("/Archives/edgar/daily-index/bulkdata/")
    ):
        raise ValueError(f"bulk redirect left the bulkdata directory: {url}")


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
    source_kind: str = "per_cik"
    source_archive_sha256: str = ""

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
        ttl_s: int = DEFAULT_CACHE_TTL_S,
    ) -> None:
        """Build a submissions client.
        Passing ``http`` bypasses construction, which is how tests inject a transport.
        """
        if http is not None:
            self.http = http
            return
        if settings is not None:
            self.http = SecHttpClient.from_settings(
                settings, cache_dir=cache_dir, ttl_s=ttl_s
            )
            return
        if not user_agent:
            raise ValueError(
                "user_agent or settings is required to build the SEC HTTP client"
            )
        self.http = SecHttpClient(
            user_agent=user_agent, cache_dir=cache_dir, ttl_s=ttl_s
        )

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


class BulkSubmissionsArchive:
    """One downloaded submissions bulk ZIP, opened for per-CIK extraction.

    The archive carries full history, shards included, so one download
    replaces the per-CIK fan-out for a bulk sync.
    """

    def __init__(
        self,
        zip_path: str | Path,
        *,
        archive_sha256: str = "",
        member_index_path: str | Path | None = None,
    ) -> None:
        self.zip_path = Path(zip_path)
        self.archive_sha256 = archive_sha256 or file_sha256(self.zip_path)
        if member_index_path is None:
            member_index_path = ensure_member_index(self.zip_path, self.archive_sha256)
        self.member_index_path = Path(member_index_path)
        self._index = MemberIndex(self.member_index_path)
        self._zip_fd = os.open(self.zip_path, os.O_RDONLY)
        self.store_reference: ArchiveReference | None = None

    @classmethod
    def download(
        cls,
        http: SecHttpClient,
        store: BulkArchiveStore,
        *,
        max_bytes: int,
    ) -> "BulkSubmissionsArchive":
        """Stream the bulk ZIP once, store it, and open the stored copy."""
        url = submissions_bulk_url()
        staging_dir = store.root / ".downloads"
        staging_dir.mkdir(parents=True, exist_ok=True)
        descriptor, staging_name = tempfile.mkstemp(
            prefix="submissions-bulk-", suffix=".zip", dir=staging_dir
        )
        staging = Path(staging_name)
        try:
            os.close(descriptor)
            result = http.stream_to_file(
                url,
                staging,
                max_response_bytes=max_bytes,
                validate_redirect=_validate_bulk_redirect,
            )
            if isinstance(result, StreamFailure):
                raise RuntimeError(
                    f"bulk archive download failed ({result.code}): {result.detail}"
                )
            reference = store.put_file(
                SUBMISSIONS_BULK_SOURCE_ID, staging, source_url=url
            )
        finally:
            staging.unlink(missing_ok=True)
        archive = cls(reference.path, archive_sha256=reference.sha256)
        archive.store_reference = reference
        return archive

    def close(self) -> None:
        self._index.close()
        os.close(self._zip_fd)

    def result_for(self, cik_padded: str) -> CikFetchResult:
        """Build one CIK's fetch result from archive members, shards included."""
        result = CikFetchResult(cik_padded=cik_padded)
        result.source_url = submissions_bulk_url()
        result.source_kind = "bulk"
        result.source_archive_sha256 = self.archive_sha256
        member_name = f"CIK{cik_padded}.json"
        raw = self._index.read_member(self._zip_fd, member_name)
        if raw is None:
            result.permanent_error = (
                f"CIK {cik_padded} is not present in the bulk archive"
            )
            return result
        result.byte_count = len(raw)
        result.response_sha256 = sha256_bytes(raw)
        payload = _parse_member(raw)
        if payload is None:
            result.permanent_error = f"bulk member {member_name} is not a JSON object"
            return result
        result.payload = payload
        result.fetched_ok = True
        for name in SubmissionsClient._historical_names(payload):
            shard_raw = self._index.read_member(self._zip_fd, name)
            if shard_raw is None:
                result.historical_errors.append(f"{name}: not present in bulk archive")
                continue
            hist_payload = _parse_member(shard_raw)
            if hist_payload is None:
                result.historical_errors.append(
                    f"{name}: not a JSON object in bulk archive"
                )
                continue
            result.historical_payloads.append(
                (historical_submissions_url(name), name, hist_payload)
            )
            result.historical_files_fetched += 1
        return result


class BulkSubmissionsClient:
    """The worker pool's ``fetch_cik`` surface over a bulk archive."""

    def __init__(self, archive: BulkSubmissionsArchive) -> None:
        self.archive = archive
        self._lock = threading.Lock()

    def fetch_cik(self, cik_padded: str) -> CikFetchResult:
        """Return the archive-sourced result for one CIK."""
        with self._lock:
            return self.archive.result_for(cik_padded)


def _parse_member(raw: bytes) -> dict | None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
