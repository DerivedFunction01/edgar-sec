"""Shared helpers for the test suite.

Fixture locations and the offline HTTP test doubles live here so that test
modules never repeat fragile ``parents[N]`` depth arithmetic, which breaks
whenever the test tree is reorganized to mirror the source tree.
"""

from __future__ import annotations

import atexit
import json
import tempfile
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from edgar_sec.domain.sec_urls import historical_submissions_url, submissions_url
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.infra.sec_http.retry import RetryPolicy
from edgar_sec.pipelines.metadata_sync.manifest import (
    CompiledCohort,
    compile_cik_cohort,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.roster import Roster, write_roster_rows
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


#: Cohort datasets built for a test live here and go when the run ends. A roster
#: is a reference to a real Parquet artifact, so a test that wants one has to have
#: a file behind it; keeping the scratch directory out of the test body is what
#: lets a test say ``roster_of(...)`` and stay about what it is testing.
_SCRATCH: list[tempfile.TemporaryDirectory[str]] = []


def roster_of(
    ciks: Iterable[str], names: Iterable[str] = (), *, name: str = "cohort.parquet"
) -> Roster:
    """Build a small cohort dataset for a test and return the roster over it.

    Prefer a test's own ``tmp_path`` when the path matters to the assertion; this
    is for the common case where the test only needs a cohort to hand to the code
    under test.
    """
    cik_list = tuple(ciks)
    name_list = tuple(names) or ("",) * len(cik_list)
    if len(name_list) != len(cik_list):
        raise ValueError("roster_of needs one name per CIK")
    scratch = tempfile.TemporaryDirectory(prefix="edgar-test-cohort-")
    _SCRATCH.append(scratch)
    roster, _digest = write_roster_rows(
        list(zip(cik_list, name_list, strict=True)),
        Path(scratch.name) / name,
    )
    return roster


atexit.register(lambda: [scratch.cleanup() for scratch in _SCRATCH])


def scratch_root() -> Path:
    """A temporary artifacts root shared by the run, for tests that only read.

    Compiling writes a dataset, so even a test that merely wants to know a
    fixture's cohort needs somewhere to put it. Use the test's own ``tmp_path``
    whenever the artifact's location is part of the assertion.
    """
    global _ROOT_SCRATCH
    if _ROOT_SCRATCH is None:
        _ROOT_SCRATCH = tempfile.TemporaryDirectory(prefix="edgar-test-root-")
        _SCRATCH.append(_ROOT_SCRATCH)
    return Path(_ROOT_SCRATCH.name)


_ROOT_SCRATCH: tempfile.TemporaryDirectory[str] | None = None


def fixture_cohort(fixture_name: str, *, limit: int | None = None) -> CompiledCohort:
    """Compile a committed CIK fixture into a throwaway cohort.

    For tests that need to know what a fixture resolves to rather than to control
    where its artifacts land.
    """
    return compile_cik_cohort(
        fixture_path(fixture_name),
        limit=limit,
        metadata_paths=resolve_metadata_paths(scratch_root()),
    )


def fixture_ciks(fixture_name: str) -> tuple[str, ...]:
    """The usable CIKs of a committed fixture, in cohort order."""
    cohort = fixture_cohort(fixture_name)
    return cohort.roster.range_ciks(0, cohort.row_count)


def compiled_cohort(
    fixture_name: str, root: str | Path, *, limit: int | None = None
) -> CompiledCohort:
    """Compile a committed CIK fixture into a cohort under a test artifacts root.

    Compiling writes a dataset, so the caller must name a root it is willing to
    have written into -- normally the test's own ``tmp_path``.
    """
    return compile_cik_cohort(
        fixture_path(fixture_name),
        limit=limit,
        metadata_paths=resolve_metadata_paths(root),
    )


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
    "compiled_cohort",
    "fixture_ciks",
    "fixture_cohort",
    "fixture_path",
    "historical_url",
    "load_catalog_fixture",
    "load_fixture",
    "roster_of",
    "scratch_root",
    "submissions_document",
]
