"""Fixture paths and offline HTTP doubles, so no test repeats ``parents[N]`` depth
arithmetic that breaks when the tree is reorganized.
"""

from __future__ import annotations

import atexit
import json
import tempfile
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa

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
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_path(name: str) -> Path:
    return FIXTURES / name


def catalog_fixture_path(name: str) -> Path:
    return CATALOG_FIXTURES / name


def load_catalog_fixture(name: str) -> Any:
    return json.loads((CATALOG_FIXTURES / name).read_text(encoding="utf-8"))


def submissions_document(cik_padded: str) -> str:
    return submissions_url(cik_padded)


def historical_url(name: str) -> str:
    return historical_submissions_url(name)


def cik_payload(cik: str, name: str, accession: str | None = None) -> dict[str, Any]:
    """A well-formed row is enough here; golden replay tests use the real fixtures."""
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


#: A roster references a real Parquet artifact, so these scratch dirs go at exit.
_SCRATCH: list[tempfile.TemporaryDirectory[str]] = []


def roster_of(
    ciks: Iterable[str], names: Iterable[str] = (), *, name: str = "cohort.parquet"
) -> Roster:
    """Prefer a test's own ``tmp_path`` when the path matters to the assertion."""
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


def era_submission_metadata(destination: Path) -> Path:
    """Copy the committed catalog fixture with pre-2005 filings appended.

    Its rows pin the candidate window's edges and a co-filer group.
    """
    import pyarrow.parquet as pq

    table = pq.read_table(catalog_fixture_path("sample_submission_metadata.parquet"))
    filings = table.column("filings").to_pylist()
    template = filings[0][0]
    appended: dict[str, list[dict[str, Any]]] = {}

    for cik, accession, filing_date, form, primary_document in ERA_FILINGS:
        row = dict(template)
        row.update(
            accession_number=accession,
            accession_number_normalized=accession.replace("-", ""),
            filing_date=filing_date,
            report_date="",
            acceptance_datetime=f"{filing_date}T16:30:00.000Z",
            form=form,
            file_number="",
            film_number="",
            items=[],
            core_type="",
            size=None,
            is_xbrl=None,
            is_inline_xbrl=None,
            is_xbrl_numeric=None,
            primary_document=primary_document,
            primary_doc_description=primary_document,
            archive_url="",
            source_section="recent",
            source_array_index=len(appended.get(cik, ())) + 900,
        )
        appended.setdefault(cik, []).append(row)

    patched = [
        list(filings[index]) + appended.get(str(table.column("cik")[index].as_py()), [])
        for index in range(table.num_rows)
    ]
    pq.write_table(
        table.set_column(
            table.schema.get_field_index("filings"), "filings", pa.array(patched)
        ),
        destination,
    )
    return destination


#: ``(cik, accession, filing_date, form, primary_document)``. The first two rows are
#: co-filers of one document with agreeing dates; the rest pin the window's edges.
ERA_FILINGS: tuple[tuple[str, str, str, str, str], ...] = (
    ("0000320193", "0000320193-02-000123", "2002-05-15", "10-K", "ex21.txt"),
    ("0000789019", "0000320193-02-000123", "2002-05-15", "10-K", "ex21.txt"),
    ("0001326801", "0001326801-04-000077", "2004-12-31", "8-K", "ex99.txt"),
    ("0001652044", "0001652044-01-000011", "2000-01-01", "10-K", "annual-report.htm"),
    ("0000019617", "0000019617-05-000045", "2005-06-01", "10-K", "ex99.txt"),
)


def scratch_root() -> Path:
    """Compiling writes a dataset, so read-only tests still need somewhere to put it."""
    global _ROOT_SCRATCH
    if _ROOT_SCRATCH is None:
        _ROOT_SCRATCH = tempfile.TemporaryDirectory(prefix="edgar-test-root-")
        _SCRATCH.append(_ROOT_SCRATCH)
    return Path(_ROOT_SCRATCH.name)


_ROOT_SCRATCH: tempfile.TemporaryDirectory[str] | None = None


def fixture_cohort(fixture_name: str, *, limit: int | None = None) -> CompiledCohort:
    """For tests that need what a fixture resolves to, not where it lands."""
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
    """The caller must name a root it accepts writes into."""
    return compile_cik_cohort(
        fixture_path(fixture_name),
        limit=limit,
        metadata_paths=resolve_metadata_paths(root),
    )


def published_universe(
    root: str | Path, fixture_name: str = "cik_lookup_universe_mini.txt"
) -> Path:
    """Publish and compile a registrant universe under ``root``; return its dataset.

    Goes through the real publish and compile path, on the committed mini fixture.
    """
    from edgar_sec.pipelines.metadata_sync.source_registry import (
        SOURCE_UNIVERSE_URL,
        refresh_cik_lookup_universe,
    )
    from edgar_sec.pipelines.metadata_sync.universe import compile_universe_cohort

    session = FakeSession()
    session.register_bytes(SOURCE_UNIVERSE_URL, fixture_path(fixture_name).read_bytes())
    metadata_paths = resolve_metadata_paths(root)
    manifest = refresh_cik_lookup_universe(
        metadata_paths=metadata_paths, client=build_test_http(session)
    )
    roster = compile_universe_cohort(
        metadata_paths, source_snapshot_id=str(manifest["snapshot_id"])
    )
    assert roster.dataset is not None
    return roster.dataset


class FakeResponse:
    def __init__(
        self, status_code: int = 200, content: bytes = b"{}", headers: Any = None
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    """Thread-safe because workers fetch concurrently; an unknown URL 404s."""

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
    """Pacing collapses to near-zero; retry, cache, and ledger still run for real."""
    return SecHttpClient(
        user_agent="TestClient/1.0 test@example.com",
        rate_limiter=RateLimiter(min_interval_s=0.001),
        retry_policy=RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0),
        timeout_s=1.0,
        session_factory=lambda: session,
    )


def build_test_client(session: FakeSession) -> SubmissionsClient:
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
