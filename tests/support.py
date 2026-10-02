"""Shared helpers for the test suite.

Fixture locations and the offline HTTP test doubles live here so that test
modules never repeat fragile ``parents[N]`` depth arithmetic, which breaks
whenever the test tree is reorganized to mirror the source tree.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from edgar_sec.domain.sec_urls import historical_submissions_url, submissions_url
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.infra.sec_http.retry import RetryPolicy
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient

TESTS_ROOT = Path(__file__).resolve().parent
FIXTURES = TESTS_ROOT / "fixtures"
CATALOG_FIXTURES = FIXTURES / "catalog"


def load_fixture(name: str) -> Any:
    """Load a committed golden fixture by filename."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_path(name: str) -> Path:
    """Return the path of a committed golden fixture."""
    return FIXTURES / name


def catalog_fixture_path(name: str) -> Path:
    """Return the path of a committed filing-catalog oracle fixture."""
    return CATALOG_FIXTURES / name


def load_catalog_fixture(name: str) -> Any:
    """Load a committed filing-catalog oracle fixture by filename."""
    return json.loads((CATALOG_FIXTURES / name).read_text(encoding="utf-8"))


def submissions_document(cik_padded: str) -> str:
    """Submissions endpoint URL for a zero-padded CIK."""
    return submissions_url(cik_padded)


def historical_url(name: str) -> str:
    """Historical submissions file URL."""
    return historical_submissions_url(name)


def cik_payload(cik: str, name: str, accession: str | None = None) -> dict[str, Any]:
    """Build a minimal but valid submissions payload for one CIK.

    Used where a test only needs a well-formed row and the exact SEC payload
    shape is irrelevant; golden replay tests should use the real fixtures.
    """
    accession = accession or f"{cik}-26-000001"
    return {
        "name": name,
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "filingDate": ["2026-01-02"],
                "form": ["10-K"],
                "size": [1024],
            },
            "files": [],
        },
    }


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(
        self, status_code: int = 200, content: bytes = b"{}", headers: Any = None
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    """Scripted URL-to-payload session recording every requested URL.

    Thread-safe because the pipeline worker fetches CIKs concurrently. An
    unregistered URL returns 404 so the permanent-failure path is exercised.
    """

    def __init__(self) -> None:
        self.payloads: dict[str, Any] = {}
        self.raw: dict[str, bytes] = {}
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def register(self, url: str, payload: Any) -> None:
        with self._lock:
            self.payloads[url] = payload

    def register_bytes(self, url: str, content: bytes) -> None:
        with self._lock:
            self.raw[url] = content

    def get(self, url: str, headers: Any = None, timeout: Any = None) -> FakeResponse:
        with self._lock:
            self.calls.append(url)
            if url in self.raw:
                return FakeResponse(200, self.raw[url])
            if url in self.payloads:
                return FakeResponse(200, json.dumps(self.payloads[url]).encode("utf-8"))
        return FakeResponse(404, b"not found")


def build_test_http(session: FakeSession) -> SecHttpClient:
    """Build a real SEC HTTP client whose transport is a scripted session.

    Pacing and backoff are collapsed to near-zero so tests stay fast, while
    retry classification, caching, and the failure ledger still run for real.
    """
    return SecHttpClient(
        user_agent="TestClient/1.0 test@example.com",
        rate_limiter=RateLimiter(min_interval_s=0.001),
        retry_policy=RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0),
        timeout_s=1.0,
        session_factory=lambda: session,
    )


def build_test_client(session: FakeSession) -> SubmissionsClient:
    """Build a submissions client bound to the scripted session."""
    return SubmissionsClient(http=build_test_http(session))


__all__ = [
    "CATALOG_FIXTURES",
    "FIXTURES",
    "TESTS_ROOT",
    "FakeResponse",
    "FakeSession",
    "build_test_client",
    "build_test_http",
    "catalog_fixture_path",
    "cik_payload",
    "fixture_path",
    "historical_url",
    "load_catalog_fixture",
    "load_fixture",
    "submissions_document",
]
